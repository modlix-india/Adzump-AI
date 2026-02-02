import os
import pickle
import math
import io
import structlog
import httpx
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any, Optional
from sentence_transformers import SentenceTransformer
from mlops.google_search.performance.prediction_schemas import (
    PerformancePredictionData,
)
from exceptions.custom_exceptions import PredictionException, ModelNotLoadedException

logger = structlog.get_logger()


class AdPerformancePredictor:
    """Service for predicting ad performance using trained LightGBM models."""

    def __init__(
        self,
        lgbm_model_path: str,
        sigmas_path: str,
        columns_path: str,
    ):
        self.lgbm_model_path = lgbm_model_path
        self.sigmas_path = sigmas_path
        self.columns_path = columns_path

        self.models: Optional[Dict[str, Any]] = None
        self.uncertainty_sigmas: Optional[Dict[str, float]] = None
        self.reference_columns: Optional[Dict[str, List[str]]] = None
        self.sentence_model: Optional[SentenceTransformer] = None
        self._is_loaded = False

    async def _load_artifact(self, path: str, description: str) -> Any:
        """
        Load a pickled artifact from a file path or URL.

        Unpickled Python object.
        """
        try:
            if path.startswith("http://") or path.startswith("https://"):
                logger.info(
                    "performance_model_downloading_artifact",
                    description=description,
                    url=path,
                    model="performance_prediction",
                )
                async with httpx.AsyncClient() as client:
                    response = await client.get(path, timeout=30)
                    response.raise_for_status()
                    return pickle.load(io.BytesIO(response.content))
            else:
                if not os.path.exists(path):
                    raise FileNotFoundError(f"{description} not found: {path}")
                with open(path, "rb") as f:
                    return pickle.load(f)
        except Exception as e:
            raise PredictionException(
                message=f"Failed to load {description}",
                details={"path": path, "original_error": str(e)},
            )

    async def load_models(self) -> None:
        """
        Load models and artifacts from pickle files or URLs.
        Raises exception if loading fails.
        """
        if self._is_loaded:
            return

        # Load artifacts using helper
        self.models = await self._load_artifact(self.lgbm_model_path, "LightGBM models")
        self.uncertainty_sigmas = await self._load_artifact(
            self.sigmas_path, "Uncertainty sigmas"
        )
        self.reference_columns = await self._load_artifact(
            self.columns_path, "Reference columns"
        )

        # Load SentenceTransformer for keyword embeddings
        self._load_sentence_transformer()

        self._is_loaded = True

    def _load_sentence_transformer(self) -> None:
        """Load SentenceTransformer model."""
        try:
            self.sentence_model = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as e:
            raise PredictionException(
                message="Failed to load SentenceTransformer model",
                details={"error": str(e)},
            )

    def predict(
        self,
        keyword_data: List[Dict[str, str]],
        total_budget: float,
        bid_strategy: str,
        period: str = "Monthly",
    ) -> PerformancePredictionData:
        """
        Predict performance ranges for keywords using batch processing.

        Dict containing predicted ranges for impressions, clicks, conversions.
        """
        if not self._is_loaded:
            raise ModelNotLoadedException(
                "Models not loaded. Call load_models() first."
            )

        if not keyword_data:
            raise ValueError("keyword_data cannot be empty")

        if period not in ["Weekly", "Monthly"]:
            raise ValueError("period must be 'Weekly' or 'Monthly'")

        # Prepare batch inputs
        keywords = [item["keyword"] for item in keyword_data]
        match_types = [item["match_type"] for item in keyword_data]
        budget_per_kw = total_budget / len(keyword_data)

        # Batch encode embeddings (Eliminates the loop for encoding)
        embeddings = self.sentence_model.encode(keywords)

        # Vectorized feature engineering
        now = datetime.now()
        base_features = {
            "Year": now.year,
            "Month": now.month,
            "Week_of_Year": now.isocalendar()[1],
            "Cost": budget_per_kw,
        }

        # Create DataFrame from base features for all keywords
        X_batch = pd.DataFrame([base_features] * len(keyword_data))

        # Add embeddings (vectorized)
        emb_cols = [f"Keyword_Embedding_{i}" for i in range(embeddings.shape[1])]
        emb_df = pd.DataFrame(embeddings, columns=emb_cols)
        X_batch = pd.concat([X_batch, emb_df], axis=1)

        # Add one-hot encoded strategy and match types (vectorized)
        X_batch[f"Ad_Group_Bid_Strategy_Type_{bid_strategy}"] = 1
        for m_type in set(match_types):
            X_batch.loc[
                [i for i, mt in enumerate(match_types) if mt == m_type],
                f"Search_Terms_Match_Type_{m_type}",
            ] = 1

        # Align with model columns once for the whole batch
        ref_columns = (
            self.reference_columns["monthly_columns"]
            if period == "Monthly"
            else self.reference_columns["weekly_columns"]
        )
        X_batch = X_batch.reindex(columns=ref_columns, fill_value=0)

        # Batch Predictions and Aggregation
        aggregated_metrics = {
            "Impressions": 0.0,
            "Clicks": 0.0,
            "Conversions": 0.0,
        }

        for target in ["Impressions", "Clicks", "Conversions"]:
            model_key = f"{period}_{target}_Model"
            if model_key in self.models:
                # Predict for all keywords in one call
                preds_log = self.models[model_key].predict(X_batch)
                sigma = self.uncertainty_sigmas[model_key]

                # Calculate range bounds and take their average as the point estimate
                # This provides a more intuitive "middle" than the raw median.
                lows = np.expm1(preds_log - sigma)
                highs = np.expm1(preds_log + sigma)
                mid_estimates = (lows + highs) / 2

                aggregated_metrics[target] = float(np.sum(mid_estimates))

        return self._format_prediction_response(
            aggregated_metrics, total_budget, period
        )

    def _format_prediction_response(
        self,
        aggregated_metrics: Dict[str, float],
        total_budget: float,
        period: str,
    ) -> Dict[str, str]:
        """
        Calculates derived metrics and formats the final response dictionary using single point estimates.
        Uses math.ceil for base metrics to ensure consistent UI math and optimistic reporting.
        """
        # 1. Extract values and apply "Ceil" rounding for higher values / UI consistency
        impressions = math.ceil(max(0, aggregated_metrics["Impressions"]))
        clicks = math.ceil(max(0, aggregated_metrics["Clicks"]))
        conversions = math.ceil(max(0, aggregated_metrics["Conversions"]))

        # 2. Calculate Derived Metrics (Averages)
        # CTR = (Clicks / Impressions) * 100
        ctr = (clicks / impressions * 100) if impressions > 0 else 0

        # CPA = Total Budget / Conversions
        cpa = (total_budget / conversions) if conversions > 0 else 0

        # Conv Rate = (Conversions / Clicks) * 100
        cv_rate = (conversions / clicks * 100) if clicks > 0 else 0

        # 3. Construct response
        return PerformancePredictionData(
            timeframe=period,
            budget_allocated=f"₹{total_budget:,.0f}",
            impressions=self._format_metric(impressions),
            clicks=self._format_metric(clicks),
            conversions=self._format_metric(conversions),
            ctr=self._format_metric(ctr, is_percent=True),
            cpa=self._format_metric(cpa, is_currency=True),
            conversion_rate=self._format_metric(cv_rate, is_percent=True),
        )

    def _format_metric(
        self,
        val: float,
        is_percent: bool = False,
        is_currency: bool = False,
    ) -> str:
        """Helper for formatting single metric values with symbols."""
        prefix = "₹" if is_currency else ""
        suffix = "%" if is_percent else ""

        if is_percent:
            return f"{val:.2f}{suffix}"

        return f"{prefix}{round(val):,}{suffix}"

    def is_ready(self) -> bool:
        """Check if predictor is loaded."""
        return self._is_loaded
