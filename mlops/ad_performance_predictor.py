"""
Ad Performance Predictor Service

Loads LightGBM models to predict ad performance ranges (impressions, clicks, conversions).
"""

import os
import pickle
import structlog
from datetime import datetime
from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

logger = structlog.get_logger()


class AdPerformancePredictor:
    """Service for predicting ad performance using trained LightGBM models."""

    def __init__(self, model_dir: str):
        """
        Initialize predictor with model directory.

        Args:
            model_dir: Path to directory containing pickle files.
        """
        self.model_dir = model_dir
        self.models: Optional[Dict[str, Any]] = None
        self.uncertainty_sigmas: Optional[Dict[str, float]] = None
        self.reference_columns: Optional[Dict[str, List[str]]] = None
        self.sentence_model: Optional[SentenceTransformer] = None
        self._is_loaded = False

    def load_models(self) -> None:
        """
        Load models and artifacts from pickle files.
        Raises FileNotFoundError if files are missing.
        """
        if self._is_loaded:
            return

        # Load LightGBM models
        models_path = os.path.join(self.model_dir, "lgbm_models.pkl")
        if not os.path.exists(models_path):
            logger.error(f"Models file not found: {models_path}")
            raise FileNotFoundError(f"Models file not found: {models_path}")
        with open(models_path, "rb") as f:
            self.models = pickle.load(f)

        # Load uncertainty sigmas
        sigmas_path = os.path.join(self.model_dir, "uncertainty_sigmas.pkl")
        if not os.path.exists(sigmas_path):
            logger.error(f"Sigmas file not found: {sigmas_path}")
            raise FileNotFoundError(f"Sigmas file not found: {sigmas_path}")
        with open(sigmas_path, "rb") as f:
            self.uncertainty_sigmas = pickle.load(f)

        # Load reference columns for feature alignment
        columns_path = os.path.join(self.model_dir, "reference_columns.pkl")
        if not os.path.exists(columns_path):
            logger.error(f"Columns file not found: {columns_path}")
            raise FileNotFoundError(f"Columns file not found: {columns_path}")
        with open(columns_path, "rb") as f:
            self.reference_columns = pickle.load(f)

        # Load SentenceTransformer for keyword embeddings
        self._load_sentence_transformer()

        self._is_loaded = True

    def _load_sentence_transformer(self) -> None:
        """Load SentenceTransformer model."""
        try:
            self.sentence_model = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as e:
            logger.error(f"Failed to load SentenceTransformer: {e}")
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

        Args:
            keyword_data: List of dicts with 'keyword' and 'match_type'.
            total_budget: Total campaign budget.
            strategy: Bid strategy (e.g., 'Maximize Conversions').
            period: 'Weekly' or 'Monthly'.

        Returns:
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
