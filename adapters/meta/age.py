# adapters/meta/age.py
import asyncio

from adapters.meta.client import meta_client


class MetaAgeAdapter:
    def __init__(self):
        self.client = meta_client

    async def fetch_age_metrics(
        self, ad_account_id: str, client_code: str
    ) -> list[dict]:
        """
        Fetch age breakdown performance + targeting in parallel.
        Returns merged rows: one per (ad_set_id, age_range).
        """
        performance, targeting = await asyncio.gather(
            self._fetch_age_performance(ad_account_id, client_code),
            self._fetch_age_targeting(ad_account_id, client_code),
        )
        return self._combine_performance_and_targeting(performance, targeting)

    async def _fetch_age_performance(
        self, ad_account_id: str, client_code: str
    ) -> list[dict]:
        """
        GET /act_{ad_account_id}/insights
        breakdowns=age, fields=spend,clicks,conversions,...
        """
        account_id = ad_account_id.removeprefix("act_")
        response = await self.client.get(
            f"/act_{account_id}/insights",
            client_code=client_code,
            params={
                "breakdowns": "age",
                "fields": "campaign_id,campaign_name,objective,adset_id,adset_name,impressions,reach,frequency,spend,clicks,unique_clicks,ctr,unique_ctr,cpc,cpm,actions,action_values,cost_per_action_type,inline_link_clicks",
                "level": "adset",
                "date_preset": "this_month",
            },
        )
        return response.get("data", [])

    async def _fetch_age_targeting(
        self, ad_account_id: str, client_code: str
    ) -> list[dict]:
        """
        GET /act_{ad_account_id}/adsets
        fields=targeting{age_min,age_max}
        """
        account_id = ad_account_id.removeprefix("act_")
        response = await self.client.get(
            f"/act_{account_id}/adsets",
            client_code=client_code,
            params={"fields": "id,campaign_id,targeting"},
        )

        return response.get("data", [])

    def _combine_performance_and_targeting(
        self, performance: list, targeting: list
    ) -> list[dict]:
        """
        Combine Meta age performance insights with ad set targeting data.

        Returns:
        - One row per (adset_id, age bucket)
        - Includes current targeting range (age_min, age_max)
        """

        # Build lookup: adset_id → {current_min, current_max}
        targeting_lookup = {}

        for adset in targeting:
            adset_id = adset.get("id")

            targeting_data = adset.get("targeting", {})
            age_min = targeting_data.get("age_min", 18)
            age_max = targeting_data.get("age_max", 65)

            targeting_lookup[adset_id] = {
                "current_min": age_min,
                "current_max": age_max,
            }

        combined = []

        for row in performance:
            adset_id = row.get("adset_id")

            combined.append(
                {
                    **row,
                    "current_min": targeting_lookup.get(adset_id, {}).get(
                        "current_min"
                    ),
                    "current_max": targeting_lookup.get(adset_id, {}).get(
                        "current_max"
                    ),
                }
            )

        return combined
