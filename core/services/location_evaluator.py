from typing import Literal

from structlog import get_logger

from core.models.optimization import LocationRecommendation

logger = get_logger(__name__)

REMOVE_CLICK_THRESHOLD = 50
REMOVE_SPEND_THRESHOLD = 10


class LocationEvaluator:
    def evaluate_campaign(
        self,
        campaign_id: str,
        targeted_locations: dict[str, str],
        geo_metrics: dict[str, dict],
        geo_details: dict[str, dict],
    ) -> list[LocationRecommendation]:
        recommendations: list[LocationRecommendation] = []

        for geo_constant, metrics in geo_metrics.items():
            if not geo_constant:
                continue

            is_targeted = geo_constant in targeted_locations
            recommendation, reason = self._evaluate_location(metrics, is_targeted)

            geo = geo_details.get(geo_constant, {})
            location_name = geo.get("location_name", "Unknown")

            if not recommendation:
                continue

            if recommendation == "ADD" and (not location_name or location_name == "Unknown"):
                continue

            recommendations.append(LocationRecommendation(
                resource_name=targeted_locations.get(geo_constant) if is_targeted else None,
                geo_target_constant=geo_constant,
                location_name=location_name,
                country_code=geo.get("country_code"),
                location_type=geo.get("location_type"),
                campaign_id=campaign_id,
                recommendation=recommendation,
                reason=reason,
                metrics=metrics,
            ))

        logger.info(
            "Location evaluation complete",
            campaign_id=campaign_id,
            locations_evaluated=len(geo_metrics),
            recommendations=len(recommendations),
        )
        return recommendations

    def _evaluate_location(
        self,
        metrics: dict,
        is_targeted: bool,
    ) -> tuple[Literal["ADD", "REMOVE"] | None, str]:
        if is_targeted:
            conversions = metrics.get("conversions", 0)
            clicks = metrics.get("clicks", 0)
            cost = metrics.get("cost", 0)
            if (
                conversions == 0
                and clicks >= REMOVE_CLICK_THRESHOLD
                and cost > REMOVE_SPEND_THRESHOLD
            ):
                return "REMOVE", "High spend & clicks but zero conversions"
        else:
            if metrics.get("conversions", 0) > 0:
                return "ADD", "Conversions from non-targeted location"

        return None, ""
