from typing import List, Dict, Any, Optional
from core.models.optimization import (
    AgeFieldRecommendation,
    GenderFieldRecommendation,
    LocationRecommendation,
    ProximityRecommendation,
)
from adapters.google.mutation.mutation_validator import MutationValidator
from adapters.google.mutation.mutation_context import MutationContext
from adapters.google.mutation.mutation_config import CONFIG
import structlog

logger = structlog.get_logger(__name__)


class CriterionTargetingBuilder:
    def __init__(self):
        self.validator = MutationValidator()

    async def build_age_ops(
        self,
        recommendations: List[AgeFieldRecommendation],
        context: MutationContext,
    ) -> List[Dict[str, Any]]:
        operations = []
        add_count = 0
        remove_count = 0

        for age_recommendation in recommendations:
            if age_recommendation.recommendation == "ADD":
                operations.append(
                    {
                        "adGroupCriterionOperation": {
                            "create": {
                                "adGroup": f"customers/{context.account_id}/adGroups/{age_recommendation.ad_group_id}",
                                "ageRange": {"type": age_recommendation.age_range},
                                "status": "ENABLED",
                            }
                        }
                    }
                )
                add_count += 1
            elif age_recommendation.recommendation == "REMOVE":
                operations.append(
                    {
                        "adGroupCriterionOperation": {
                            "remove": age_recommendation.resource_name
                        }
                    }
                )
                remove_count += 1

        if operations:
            logger.info(
                "age_operations_built",
                adds=add_count,
                removes=remove_count,
                total_operations=len(operations),
            )
        return operations

    async def build_gender_ops(
        self,
        recommendations: List[GenderFieldRecommendation],
        context: MutationContext,
    ) -> List[Dict[str, Any]]:
        operations = []
        add_count = 0
        remove_count = 0

        for gender_recommendation in recommendations:
            if gender_recommendation.recommendation == "ADD":
                operations.append(
                    {
                        "adGroupCriterionOperation": {
                            "create": {
                                "adGroup": f"customers/{context.account_id}/adGroups/{gender_recommendation.ad_group_id}",
                                "status": "ENABLED",
                                "gender": {"type": gender_recommendation.gender_type},
                            }
                        }
                    }
                )
                add_count += 1
            elif gender_recommendation.recommendation == "REMOVE":
                operations.append(
                    {
                        "adGroupCriterionOperation": {
                            "remove": gender_recommendation.resource_name
                        }
                    }
                )
                remove_count += 1

        if operations:
            logger.info(
                "gender_operations_built",
                adds=add_count,
                removes=remove_count,
                total_operations=len(operations),
            )
        return operations

    async def build_location_ops(
        self,
        recommendations: List[LocationRecommendation],
        context: MutationContext,
    ) -> List[Dict[str, Any]]:
        operations = []
        add_count = 0
        remove_count = 0

        for loc_rec in recommendations:
            if loc_rec.recommendation == "ADD":
                if not loc_rec.geo_target_constant:
                    logger.error(
                        "Location ADD missing geo_target_constant",
                    )
                    continue

                criterion = {
                    "location": {"geoTargetConstant": loc_rec.geo_target_constant}
                }

                # CampaignCriterion does NOT support 'status'. AdGroupCriterion DOES support 'status'.
                if loc_rec.level == "AD_GROUP":
                    criterion["status"] = "ENABLED"

                if getattr(loc_rec, "negative", False):
                    criterion["negative"] = True

                operation_key = (
                    "campaignCriterionOperation"
                    if loc_rec.level == "CAMPAIGN"
                    else "adGroupCriterionOperation"
                )
                parent_key = "campaign" if loc_rec.level == "CAMPAIGN" else "adGroup"
                parent_id = (
                    loc_rec.campaign_id
                    if loc_rec.level == "CAMPAIGN"
                    else loc_rec.ad_group_id
                )

                operations.append(
                    {
                        operation_key: {
                            "create": {
                                parent_key: f"customers/{context.account_id}/{parent_key}s/{parent_id}",
                                **criterion,
                            }
                        }
                    }
                )
                add_count += 1
            elif loc_rec.recommendation == "REMOVE":
                if not loc_rec.resource_name:
                    logger.error(
                        "Location REMOVE missing resource_name",
                    )
                    continue
                op_key = (
                    "campaignCriterionOperation"
                    if "/campaignCriteria/" in loc_rec.resource_name
                    else "adGroupCriterionOperation"
                )
                operations.append({op_key: {"remove": loc_rec.resource_name}})
                remove_count += 1

        if operations:
            logger.info(
                "location_operations_built",
                adds=add_count,
                removes=remove_count,
                total_operations=len(operations),
            )
        return operations

    async def build_proximity_ops(
        self,
        recommendations: List[ProximityRecommendation],
        context: MutationContext,
    ) -> List[Dict[str, Any]]:
        """Build proximity (radius) targeting operations."""
        operations = []
        add_count = 0
        remove_count = 0

        for prox_rec in recommendations:
            if prox_rec.recommendation == "ADD":
                if not self.validator.validate_radius(proximity=prox_rec):
                    continue

                proximity_info = self._build_proximity_info(proximity=prox_rec)
                if not proximity_info:
                    continue

                criterion = {"proximity": proximity_info}

                # CampaignCriterion does NOT support 'status'.
                # AdGroupCriterion DOES support 'status'.
                if prox_rec.level == "AD_GROUP":
                    criterion["status"] = "ENABLED"

                operation_key = (
                    "campaignCriterionOperation"
                    if prox_rec.level == "CAMPAIGN"
                    else "adGroupCriterionOperation"
                )
                parent_key = "campaign" if prox_rec.level == "CAMPAIGN" else "adGroup"
                parent_id = (
                    prox_rec.campaign_id
                    if prox_rec.level == "CAMPAIGN"
                    else prox_rec.ad_group_id
                )

                operations.append(
                    {
                        operation_key: {
                            "create": {
                                parent_key: f"customers/{context.account_id}/{parent_key}s/{parent_id}",
                                **criterion,
                            },
                        }
                    }
                )
                add_count += 1
            elif prox_rec.recommendation == "REMOVE":
                if not prox_rec.resource_name:
                    logger.error("Proximity REMOVE operation missing the resource_name")
                    continue
                op_key = (
                    "campaignCriterionOperation"
                    if "/campaignCriteria/" in prox_rec.resource_name
                    else "adGroupCriterionOperation"
                )
                operations.append({op_key: {"remove": prox_rec.resource_name}})
                remove_count += 1

        if operations:
            logger.info(
                "proximity_operations_built",
                adds=add_count,
                removes=remove_count,
                total_operations=len(operations),
            )
        return operations

    def _build_proximity_info(
        self, proximity: ProximityRecommendation
    ) -> Optional[Dict[str, Any]]:
        """Build proximity info from address or coordinates."""
        # Normalize to KILOMETERS for consistency in the payload

        radius_value = (
            proximity.radius * CONFIG.PROXIMITY.MILES_TO_KM
            if proximity.radius_units == "MILES"
            else proximity.radius
        )

        proximity_info = {
            "radius": float(radius_value),
            "radiusUnits": "KILOMETERS",
        }

        if proximity.address:
            address_info = {}
            if proximity.address.street_address:
                address_info["streetAddress"] = proximity.address.street_address
            if proximity.address.city_name:
                address_info["cityName"] = proximity.address.city_name
            if proximity.address.postal_code:
                address_info["postalCode"] = proximity.address.postal_code
            if proximity.address.country_code:
                address_info["countryCode"] = proximity.address.country_code
            if address_info:
                proximity_info["address"] = address_info
                return proximity_info

        if proximity.latitude is not None and proximity.longitude is not None:
            proximity_info["geoPoint"] = {
                "longitudeInMicroDegrees": int(proximity.longitude * 1_000_000),
                "latitudeInMicroDegrees": int(proximity.latitude * 1_000_000),
            }
            return proximity_info

        logger.error("Proximity requires address or coordinates")
        return None
