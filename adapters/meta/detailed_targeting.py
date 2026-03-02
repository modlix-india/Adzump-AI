from typing import List, Dict, Any
import asyncio

from adapters.meta.client import meta_client
import structlog
logger = structlog.get_logger()

class MetaDetailedTargetingAdapter:
    """Adapter for Meta Detailed Targeting operations."""


    def _normalize_ad_account_id(self, ad_account_id: str) -> str:
        return ad_account_id.removeprefix("act_")

    async def _search(
        self,
        ad_account_id: str,
        search_type: str,
        query: str,
        client_code: str,
    ) -> List[Dict[str, Any]]:

        account_id = self._normalize_ad_account_id(ad_account_id)

        response = await meta_client.get(
            f"/act_{account_id}/targetingsearch",
            client_code=client_code,
            params={
                "type": search_type,
                "q": query,
                "limit": 5,
            },
        )

        return response.get("data", [])


    async def _resolve(
        self,
        names: List[str],
        ad_account_id: str,
        search_type: str,
        client_code: str,
    ) -> List[Dict[str, Any]]:

        tasks = [
            self._search(
                ad_account_id=ad_account_id,
                search_type=search_type,
                query=name.strip(),
                client_code=client_code,
            )
            for name in names
            if name
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        resolved_items: List[Dict[str, Any]] = []
        seen_ids = set()

        for data in results:
            if isinstance(data, Exception) or not data:
                continue

            item = data[0]

            item_id = item.get("id")
            if not item_id or item_id in seen_ids:
                continue

            seen_ids.add(item_id)

            resolved_items.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "path": item.get("path"),
                    "audience_size_lower_bound": item.get("audience_size_lower_bound"),
                    "audience_size_upper_bound": item.get("audience_size_upper_bound"),
                    "description": item.get("description"),
                }
            )

        return resolved_items

    async def build_flexible_spec(
        self,
        ad_account_id: str,
        client_code: str,
        interests: List[str] | None = None,
        behaviors: List[str] | None = None,
        demographics: List[str] | None = None,
    ) -> List[Dict[str, Any]]:

        logger.info("Interests from LLM", interests=interests)
        logger.info("Behaviors from LLM", behaviors=behaviors)
        logger.info("Demographics from LLM", demographics=demographics)

        flexible_spec = []

        if interests:
            resolved_interests = await self._resolve(
                interests,
                ad_account_id,
                "adinterest",
                client_code,
            )

            if resolved_interests:
                flexible_spec.append(
                    {
                        "interests": resolved_interests
                    }
                )


        if behaviors:
            resolved_behaviors = await self._resolve(
                behaviors,
                ad_account_id,
                "adbehavior",
                client_code,
            )

            if resolved_behaviors:
                flexible_spec.append(
                    {
                        "behaviors": resolved_behaviors
                    }
                )


        if demographics:
            resolved_demographics = await self._resolve(
                demographics,
                ad_account_id,
                "addemographic",
                client_code,
            )

            if resolved_demographics:
                flexible_spec.append(
                    {
                        "demographics": resolved_demographics
                    }
                )


        return flexible_spec
