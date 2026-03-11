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
        seen_ids: set = None,
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
        if seen_ids is None:
            seen_ids = set()

        type_mapping = {
            "adinterest": "interests",
            "addemographic": "demographics",
            "adbehavior": "behaviors"
        }
        mapped_type = type_mapping.get(search_type, search_type)

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
                    "type": mapped_type,
                    "path": [mapped_type],
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

        audience_targeting = {}
        seen_ids = set()

        if interests:
            resolved_interests = await self._resolve(
                interests,
                ad_account_id,
                "adinterest",
                client_code,
                seen_ids,
            )

            if resolved_interests:
                audience_targeting["interests"] = resolved_interests


        if behaviors:
            resolved_behaviors = await self._resolve(
                behaviors,
                ad_account_id,
                "adbehavior",
                client_code,
                seen_ids,
            )

            if resolved_behaviors:
                audience_targeting["behaviors"] = resolved_behaviors


        if demographics:
            resolved_demographics = await self._resolve(
                demographics,
                ad_account_id,
                "addemographic",
                client_code,
                seen_ids,
            )

            if resolved_demographics:
                audience_targeting["demographics"] = resolved_demographics

        logger.info(
            "meta_adset_detailed.audience_targeting_built",
            count=len(audience_targeting),
        )

        return audience_targeting
