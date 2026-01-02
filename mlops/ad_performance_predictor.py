import os
import pickle
import structlog
import requests
import io
from datetime import datetime
from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

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

    def _load_artifact(self, path: str, description: str) -> Any:
        """
        Load a pickled artifact from a file path or URL.

        Unpickled Python object.
        """
        try:
            if path.startswith("http://") or path.startswith("https://"):
                logger.info("downloading_artifact", description=description, url=path)
                response = requests.get(path, timeout=30)
                response.raise_for_status()
                return pickle.load(io.BytesIO(response.content))
            else:
                if not os.path.exists(path):
                    raise FileNotFoundError(f"{description} not found: {path}")
                with open(path, "rb") as f:
                    return pickle.load(f)
        except Exception as e:
            logger.error(
                "artifact_load_failed", description=description, path=path, error=str(e)
            )
            raise

    def load_models(self) -> None:
        """
        Load models and artifacts from pickle files or URLs.
        Raises exception if loading fails.
        """
        if self._is_loaded:
            return

        # Load artifacts using helper
        self.models = self._load_artifact(self.lgbm_model_path, "LightGBM models")
        self.uncertainty_sigmas = self._load_artifact(
            self.sigmas_path, "Uncertainty sigmas"
        )
        self.reference_columns = self._load_artifact(
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
            logger.error("sentence_transformer_load_failed", error=str(e))
            raise

    def predict(
        self,
        keyword_data: List[Dict[str, str]],
        total_budget: float,
        strategy: str,
        period: str = "Monthly",
    ) -> Dict[str, str]:
        """
        Predict performance ranges for keywords.

        Dict containing predicted ranges for impressions, clicks, conversions.
        """
        if not self._is_loaded:
            logger.error("Predict called but models not loaded")
            raise RuntimeError("Models not loaded. Call load_models() first.")

        if not keyword_data:
            raise ValueError("keyword_data cannot be empty")

        if period not in ["Weekly", "Monthly"]:
            raise ValueError("period must be 'Weekly' or 'Monthly'")

        # Distribute budget equally among keywords
        budget_per_kw = total_budget / len(keyword_data)

        # Initialize aggregated ranges
        aggregated_ranges = {
            "Impressions": [0.0, 0.0],
            "Clicks": [0.0, 0.0],
            "Conversions": [0.0, 0.0],
        }

        # Get reference columns for the period
        ref_columns = (
            self.reference_columns["monthly_columns"]
            if period == "Monthly"
            else self.reference_columns["weekly_columns"]
        )

        # Process each keyword
        for item in keyword_data:
            kw = item["keyword"]
            m_type = item["match_type"]

            # Generate keyword embedding
            embedding = self.sentence_model.encode([kw])[0]
            emb_dict = {
                f"Keyword_Embedding_{i}": val for i, val in enumerate(embedding)
            }

            # Build feature row with current date
            now = datetime.now()
            row_data = {
                "Year": now.year,
                "Month": now.month,
                "Week_of_Year": now.isocalendar()[1],  # ISO week number
                "Cost": budget_per_kw,
                **emb_dict,
            }

            # Create DataFrame and add one-hot encoded columns
            X_row = pd.DataFrame([row_data])
            X_row[f"Ad_Group_Bid_Strategy_Type_{strategy}"] = 1
            X_row[f"Search_Terms_Match_Type_{m_type}"] = 1

            # Align with training columns (adds missing as 0)
            X_row = X_row.reindex(columns=ref_columns, fill_value=0)

            # Predict for each target
            for target in ["Impressions", "Clicks", "Conversions"]:
                model_key = f"{period}_{target}_Model"
                if model_key in self.models:
                    # Predict in log-space
                    pred_log = self.models[model_key].predict(X_row)[0]
                    sigma = self.uncertainty_sigmas[model_key]

                    # Calculate range using sigma
                    low = np.expm1(pred_log - sigma)
                    high = np.expm1(pred_log + sigma)

                    aggregated_ranges[target][0] += low
                    aggregated_ranges[target][1] += high

        # Format the response
        return {
            "timeframe": period,
            "budget_allocated": f"₹{total_budget:,.0f}",
            "impressions": f"{round(max(0, aggregated_ranges['Impressions'][0])):,} - {round(aggregated_ranges['Impressions'][1]):,}",
            "clicks": f"{round(max(0, aggregated_ranges['Clicks'][0])):,} - {round(aggregated_ranges['Clicks'][1]):,}",
            "conversions": f"{round(max(0, aggregated_ranges['Conversions'][0])):,} - {round(aggregated_ranges['Conversions'][1]):,}",
        }

    def is_ready(self) -> bool:
        """Check if predictor is loaded."""
        return self._is_loaded
