import os
import pickle
import io
import requests
import structlog
import numpy as np
import pandas as pd
from typing import Any

logger = structlog.get_logger()


class BudgetPredictor:
    """Service for predicting budget using a linear regression model."""

    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model: Any = None
        self._is_loaded = False

    def _load_artifact(self, path: str, description: str) -> Any:
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

    def load_model(self) -> None:
        """Load the linear model from file or URL."""
        if self._is_loaded:
            return

        self.model = self._load_artifact(self.model_path, "Budget Linear Model")
        self._is_loaded = True

    def predict(
        self,
        clicks: int,
        conversions: int,
        duration_days: int,
        buffer_percent: float = 0.20,
    ) -> dict:
        """
        Predicts expected Cost using the linear model and applies a buffer.
        """
        if not self._is_loaded:
            logger.error("Predict called but model not loaded")
            raise RuntimeError("Model not loaded. Call load_model() first.")

        input_df = pd.DataFrame(
            {
                "TotalClicks": [clicks],
                "TotalConversions": [conversions],
                "CampaignDuration": [duration_days],
            }
        )
        input_log = np.log1p(input_df)

        try:
            pred_lin_log = self.model.predict(input_log)[0]
            cost_lin = np.expm1(pred_lin_log)
            buffered_cost_lin = cost_lin * (1.0 + buffer_percent)

            return {
                "suggested_budget": float(buffered_cost_lin),
                "base_cost_prediction": float(cost_lin),
            }
        except Exception as e:
            logger.error("budget_prediction_failed", error=str(e))
            raise

    def is_ready(self) -> bool:
        return self._is_loaded
