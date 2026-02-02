import io
import math
import pickle

import httpx
import numpy as np
import pandas as pd  # type: ignore
import structlog
from typing import Any

from exceptions.custom_exceptions import ModelNotLoadedException, PredictionException
from mlops.google_search.budget_prediction.schemas import BudgetPredictionData


logger = structlog.get_logger()


class BudgetPredictor:
    """Service for predicting budget using a linear regression model."""

    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model: Any = None
        self._is_loaded = False

    async def load_model(self) -> None:
        """Load the linear model from file or URL."""
        if self._is_loaded:
            return

        self.model = await self._load_artifact(self.model_path, "Budget Linear Model")
        self._is_loaded = True

    def predict(
        self,
        conversions: int,
        duration_days: int,
        expected_conversion_rate: float = 12.0,
        buffer_percent: float = 0.20,
    ) -> BudgetPredictionData:
        """
        Predicts expected Cost using the linear model and applies a buffer.
        """
        if not self._is_loaded:
            raise ModelNotLoadedException(
                "Budget prediction model not loaded. Call load_model() first."
            )

        # Calculate clicks from conversions based on expected conversion rate
        # Conversion rate is given as a percentage (e.g., 12.0 for 12%)
        rate_decimal = expected_conversion_rate / 100.0
        # If rate_decimal is 0, we avoid division by zero
        if rate_decimal <= 0:
            raise PredictionException(
                "Expected conversion rate must be greater than zero."
            )

        calculated_clicks = math.ceil(conversions / rate_decimal)

        input_df = pd.DataFrame(
            {
                "TotalClicks": [calculated_clicks],
                "TotalConversions": [conversions],
                "CampaignDuration": [duration_days],
            }
        )
        input_log = np.log1p(input_df)

        try:
            pred_lin_log = self.model.predict(input_log)[0]
            cost_lin = np.expm1(pred_lin_log)
            buffered_cost_lin = cost_lin * (1.0 + buffer_percent)

            return BudgetPredictionData(
                suggested_budget=int(math.ceil(buffered_cost_lin)),
                base_cost_prediction=int(math.ceil(cost_lin)),
            )
        except Exception as e:
            raise PredictionException(
                message="Budget prediction failed", details={"error": str(e)}
            )

    def is_ready(self) -> bool:
        return self._is_loaded

    async def _load_artifact(self, path: str, description: str) -> Any:
        try:
            if path.startswith("http://") or path.startswith("https://"):
                logger.info(
                    "budget_model_downloading_artifact",
                    description=description,
                    url=path,
                    model="budget_prediction",
                )
                async with httpx.AsyncClient() as client:
                    response = await client.get(path, timeout=30)
                    response.raise_for_status()
                    return pickle.load(io.BytesIO(response.content))
            else:
                with open(path, "rb") as f:
                    return pickle.load(f)
        except (
            FileNotFoundError,
            httpx.HTTPStatusError,
            httpx.RequestError,
            pickle.UnpicklingError,
            OSError,
        ) as e:
            logger.error(
                "artifact_load_failed",
                description=description,
                path=path,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise PredictionException(
                message=f"Failed to load {description}",
                details={"path": path, "original_error": str(e)},
            ) from e
