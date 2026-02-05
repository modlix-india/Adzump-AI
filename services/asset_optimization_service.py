import os
import re
import httpx
import asyncio
import numpy as np
import structlog
from typing import Tuple
from services.openai_client import generate_embeddings, chat_completion
from services.json_utils import safe_json_parse
from utils import prompt_loader

logger = structlog.get_logger(__name__)


class AssetOptimizationService:
    def __init__(self):
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.google_ads_api_version = "v20"

    async def analyze_all_campaigns(
        self, customer_id: str, access_token: str, login_customer_id: str
    ) -> dict:
        logger.info(
            "Starting bulk campaign analysis",
            customer_id=customer_id,
            step="bulk_analysis_start",
        )

        # Step 1: Fetch all campaigns
        campaigns = await self._fetch_all_campaigns(
            customer_id, access_token, login_customer_id
        )

        logger.info(
            "Campaigns fetched for bulk analysis",
            step="campaigns_fetched",
            total_campaigns=len(campaigns),
        )

        if not campaigns:
            return {
                "customer_id": customer_id,
                "total_campaigns": 0,
                "successful": 0,
                "failed": 0,
                "results": [],
                "errors": [],
                "message": "No campaigns found for this customer",
            }

        # Step 2: Analyze campaigns in parallel

        tasks = []
        for campaign in campaigns:
            task = self.analyze_campaign(
                customer_id=customer_id,
                campaign_id=campaign["id"],
                access_token=access_token,
                login_customer_id=login_customer_id,
            )
            tasks.append(task)

        # Gather with exception handling
        results_with_errors = await asyncio.gather(*tasks, return_exceptions=True)

        # Separate successful results from errors
        successful_results = []
        errors = []

        for idx, result in enumerate(results_with_errors):
            campaign = campaigns[idx]
            if isinstance(result, Exception):
                errors.append(
                    {
                        "campaign_id": campaign["id"],
                        "campaign_name": campaign["name"],
                        "error": str(result),
                    }
                )
                logger.error(
                    "Campaign analysis failed",
                    campaign_id=campaign["id"],
                    error=str(result),
                )
            else:
                successful_results.append(result)
                logger.info(
                    "Campaign analysis succeeded",
                    campaign_id=campaign["id"],
                    suggestions_count=result.get("total_suggestions", 0),
                )

        summary = {
            "customer_id": customer_id,
            "total_campaigns": len(campaigns),
            "successful": len(successful_results),
            "failed": len(errors),
            "results": successful_results,
            "errors": errors,
        }

        logger.info(
            "Bulk campaign analysis completed",
            step="bulk_analysis_complete",
            total_campaigns=summary["total_campaigns"],
            successful=summary["successful"],
            failed=summary["failed"],
        )

        return summary

    async def analyze_campaign(
        self,
        customer_id: str,
        campaign_id: str,
        access_token: str,
        login_customer_id: str,
    ) -> dict:
        logger.info(
            "Starting campaign analysis",
            customer_id=customer_id,
            campaign_id=campaign_id,
        )

        # Step 1: Fetch performance data
        logger.info("Fetching asset performance data", step="fetch_performance")
        performance_data = await self._fetch_asset_performance(
            customer_id, campaign_id, access_token, login_customer_id
        )
        logger.info(
            "Performance data fetched",
            step="fetch_performance_complete",
            total_results=len(performance_data),
        )

        if not performance_data:
            return {
                "campaign_id": campaign_id,
                "campaign_name": "",
                "total_low_assets": 0,
                "suggestions": [],
                "message": "No asset performance data found for this campaign",
            }

        # Step 2: Extract asset IDs and fetch text
        asset_ids = list(
            set(
                [
                    item.get("adGroupAdAssetView", {}).get("asset", "").split("/")[-1]
                    for item in performance_data
                ]
            )
        )

        logger.info(
            "Fetching asset text", step="fetch_asset_text", asset_count=len(asset_ids)
        )
        asset_details = await self._fetch_asset_text(
            asset_ids, customer_id, access_token, login_customer_id
        )
        logger.info(
            "Asset text fetched",
            step="fetch_asset_text_complete",
            assets_retrieved=len(asset_details),
        )

        # Step 3: Categorize assets into tiers
        logger.info("Categorizing assets", step="categorize_assets")
        categorized = self._categorize_assets(performance_data, asset_details)
        logger.info(
            "Assets categorized",
            step="categorize_complete",
            low_count=len(categorized["low_assets"]),
            tier_1_count=len(categorized["tier_1"]),
            tier_2_count=len(categorized["tier_2"]),
            tier_3_count=len(categorized["tier_3"]),
        )

        if not categorized["low_assets"]:
            return {
                "campaign_id": campaign_id,
                "campaign_name": performance_data[0]
                .get("campaign", {})
                .get("name", ""),
                "total_low_assets": 0,
                "suggestions": [],
                "message": "Great news! All assets are performing well. No optimizations needed.",
                "status": "optimized",
            }

        logger.info(
            "Found assets",
            low=len(categorized["low_assets"]),
            tier_1=len(categorized["tier_1"]),
            tier_2=len(categorized["tier_2"]),
            tier_3=len(categorized["tier_3"]),
        )

        # Step 4: Generate suggestions for each LOW asset
        suggestions = []

        for idx, low_asset in enumerate(categorized["low_assets"], 1):
            try:
                logger.info(
                    "Processing LOW asset",
                    step="process_low_asset",
                    progress=f"{idx}/{len(categorized['low_assets'])}",
                    asset_id=low_asset["asset_id"],
                    asset_type=low_asset["asset_type"],
                    text=low_asset["text"][:50] + "..."
                    if len(low_asset["text"]) > 50
                    else low_asset["text"],
                )

                # Find similar assets with fallback
                similar_assets, source_tier = await self._find_similar_assets(
                    low_asset["text"],
                    categorized,
                    low_asset["asset_type"],
                    low_asset["campaign_name"],
                    low_asset["ad_group_name"],
                )
                logger.info(
                    "Similar assets found",
                    step="find_similar_complete",
                    asset_id=low_asset["asset_id"],
                    similar_count=len(similar_assets),
                    source_tier=source_tier,
                )

                # Generate suggestions
                logger.info(
                    "Generating suggestions",
                    step="generate_suggestions",
                    asset_id=low_asset["asset_id"],
                )
                new_options = await self._generate_suggestions(
                    low_asset,
                    similar_assets,
                    source_tier,
                    low_asset["campaign_name"],
                    low_asset["ad_group_name"],
                )
                logger.info(
                    "Suggestions generated",
                    step="generate_suggestions_complete",
                    asset_id=low_asset["asset_id"],
                    raw_count=len(new_options),
                )

                # Validate
                logger.info(
                    "Validating suggestions",
                    step="validate_suggestions",
                    asset_id=low_asset["asset_id"],
                )
                validated_options = self._validate_suggestions(
                    new_options, low_asset["asset_type"]
                )
                logger.info(
                    "Suggestions validated",
                    step="validate_complete",
                    asset_id=low_asset["asset_id"],
                    validated_count=len(validated_options),
                    rejected_count=len(new_options) - len(validated_options),
                )

                if validated_options:
                    # Add the "remove" item for the LOW asset
                    suggestions.append(
                        {
                            "id": low_asset["asset_id"],
                            "type": low_asset["asset_type"],
                            "text": low_asset["text"],
                            "label": "remove",
                            "reason": f"LOW performance ({low_asset['impressions']} impressions)",
                            "ad_group_id": low_asset["ad_group_id"],
                            "ad_id": low_asset.get("ad_id", ""),
                            "campaign_id": campaign_id,
                            "performance_label": low_asset["label"],
                            "impressions": low_asset["impressions"],
                            "based_on": source_tier,
                        }
                    )

                    # Add only the BEST validated option (1:1 replacement)
                    best_option = validated_options[0]
                    suggestions.append(
                        {
                            "id": None,  # New asset, no ID yet
                            "type": low_asset["asset_type"],
                            "text": best_option["text"],
                            "label": "add",
                            "reason": f"Replacement for LOW asset (generated from {source_tier})",
                            "ad_group_id": low_asset["ad_group_id"],
                            "ad_id": low_asset.get("ad_id", ""),
                            "campaign_id": campaign_id,
                            "character_count": best_option["character_count"],
                            "replaces_asset_id": low_asset["asset_id"],
                            "based_on": source_tier,
                        }
                    )

            except Exception as e:
                logger.error(
                    "Failed to generate suggestions for asset",
                    asset_id=low_asset["asset_id"],
                    error=str(e),
                )

        result = {
            "campaign_id": campaign_id,
            "campaign_name": categorized["low_assets"][0]["campaign_name"]
            if categorized["low_assets"]
            else "",
            "total_low_assets": len(categorized["low_assets"]),
            "total_suggestions": len(suggestions),
            "suggestions": suggestions,
        }

        logger.info(
            "Campaign analysis completed",
            step="analysis_complete",
            total_low_assets=result["total_low_assets"],
            total_suggestions=result["total_suggestions"],
            suggestions_per_asset=round(
                result["total_suggestions"] / result["total_low_assets"], 1
            )
            if result["total_low_assets"] > 0
            else 0,
        )

        return result

    async def _fetch_asset_performance(
        self,
        customer_id: str,
        campaign_id: str,
        access_token: str,
        login_customer_id: str,
    ) -> list:
        url = f"https://googleads.googleapis.com/{self.google_ads_api_version}/customers/{customer_id}/googleAds:search"

        query = f"""
            SELECT 
                campaign.id, campaign.name,
                ad_group.id, ad_group.name,
                ad_group_ad.ad.id,
                ad_group_ad_asset_view.asset,
                ad_group_ad_asset_view.field_type,
                ad_group_ad_asset_view.performance_label,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros
            FROM ad_group_ad_asset_view
            WHERE ad_group_ad.ad.type = RESPONSIVE_SEARCH_AD
              AND segments.date DURING LAST_30_DAYS
              AND campaign.id = {campaign_id}
              AND ad_group_ad_asset_view.field_type IN (HEADLINE, DESCRIPTION)
        """

        headers = {
            "authorization": f"Bearer {access_token}",
            "developer-token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "login-customer-id": login_customer_id,
            "content-type": "application/json",
        }

        payload = {"query": query}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                return response.json().get("results", [])
        except Exception as e:
            logger.error("Failed to fetch asset performance", error=str(e))
            raise

    async def _fetch_all_campaigns(
        self, customer_id: str, access_token: str, login_customer_id: str
    ) -> list:
        url = f"https://googleads.googleapis.com/{self.google_ads_api_version}/customers/{customer_id}/googleAds:search"

        query = """
            SELECT 
                campaign.id,
                campaign.name,
                campaign.status
            FROM campaign
            WHERE campaign.status = ENABLED
              AND campaign.advertising_channel_type = SEARCH
        """

        headers = {
            "authorization": f"Bearer {access_token}",
            "developer-token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "login-customer-id": login_customer_id,
            "content-type": "application/json",
        }

        all_campaigns = []
        next_page_token = None
        page_num = 1

        try:
            # Pagination loop
            while True:
                payload = {"query": query}

                # Add page token if this is not the first page
                if next_page_token:
                    payload["pageToken"] = next_page_token

                logger.info(
                    "Fetching campaigns page", customer_id=customer_id, page=page_num
                )

                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    data = response.json()

                results = data.get("results", [])

                for result in results:
                    campaign_data = result.get("campaign", {})
                    all_campaigns.append(
                        {
                            "id": str(campaign_data.get("id", "")),
                            "name": campaign_data.get("name", ""),
                            "status": campaign_data.get("status", ""),
                        }
                    )

                logger.info(
                    "Campaigns page fetched",
                    page=page_num,
                    campaigns_in_page=len(results),
                    total_so_far=len(all_campaigns),
                )

                # Check if there's a next page
                next_page_token = data.get("nextPageToken")
                if not next_page_token:
                    break  # No more pages

                page_num += 1

            logger.info(
                "All campaigns fetched",
                customer_id=customer_id,
                total_campaigns=len(all_campaigns),
                total_pages=page_num,
            )

            return all_campaigns

        except Exception as e:
            logger.error("Failed to fetch campaigns", error=str(e))
            raise

    async def _fetch_asset_text(
        self,
        asset_ids: list,
        customer_id: str,
        access_token: str,
        login_customer_id: str,
    ) -> dict:
        if not asset_ids:
            return {}

        # Filter out empty IDs
        valid_ids = [aid for aid in asset_ids if aid]
        if not valid_ids:
            return {}

        url = f"https://googleads.googleapis.com/{self.google_ads_api_version}/customers/{customer_id}/googleAds:search"

        ids_str = ", ".join(valid_ids)
        query = f"""
            SELECT asset.id, asset.name, asset.text_asset.text, asset.type
            FROM asset
            WHERE asset.id IN ({ids_str})
        """

        headers = {
            "authorization": f"Bearer {access_token}",
            "developer-token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "login-customer-id": login_customer_id,
            "content-type": "application/json",
        }

        payload = {"query": query}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                results = response.json().get("results", [])

            # Convert to dict: asset_id -> text
            asset_map = {}
            for result in results:
                asset = result.get("asset", {})
                asset_id = asset.get("id")
                text = asset.get("textAsset", {}).get("text", "")
                if asset_id and text:
                    asset_map[str(asset_id)] = text

            return asset_map

        except Exception as e:
            logger.error("Failed to fetch asset text", error=str(e))
            return {}

    def _categorize_assets(self, performance_data: list, asset_details: dict) -> dict:
        low_assets = []
        tier_1 = []  # GOOD/BEST
        tier_2 = []  # LEARNING/PENDING
        tier_3 = []  # Other

        for item in performance_data:
            label = item.get("adGroupAdAssetView", {}).get("performanceLabel")

            asset_resource = item.get("adGroupAdAssetView", {}).get("asset", "")
            asset_id = asset_resource.split("/")[-1]

            asset_type = item.get("adGroupAdAssetView", {}).get("fieldType")
            impressions = int(item.get("metrics", {}).get("impressions", 0))

            # Extract ad ID - API returns id directly
            ad_data = item.get("adGroupAd", {}).get("ad", {})
            ad_id = ad_data.get("id", "") if isinstance(ad_data, dict) else ""

            text = asset_details.get(asset_id, "")
            if not text:
                continue  # Skip assets without text

            asset_obj = {
                "asset_id": asset_id,
                "asset_type": asset_type,
                "text": text,
                "impressions": impressions,
                "label": label or "UNKNOWN",
                "ad_group_id": item.get("adGroup", {}).get("id"),
                "ad_group_name": item.get("adGroup", {}).get("name"),
                "campaign_name": item.get("campaign", {}).get("name"),
                "ad_id": ad_id,
            }

            # Categorize into tiers
            if label == "LOW":
                low_assets.append(asset_obj)
            elif label in ["GOOD", "BEST"]:
                tier_1.append(asset_obj)
            elif label in ["LEARNING", "PENDING"]:
                tier_2.append(asset_obj)
            else:
                tier_3.append(asset_obj)

        return {
            "low_assets": low_assets,
            "tier_1": tier_1,
            "tier_2": tier_2,
            "tier_3": tier_3,
        }

    async def _find_similar_assets(
        self,
        low_asset_text: str,
        categorized_assets: dict,
        asset_type: str,
        campaign_name: str = "",
        ad_group_name: str = "",
    ) -> Tuple[list, str]:
        # Try each tier in priority order
        for tier_name, tier_assets in [
            ("tier_1", categorized_assets["tier_1"]),
            ("tier_2", categorized_assets["tier_2"]),
            ("tier_3", categorized_assets["tier_3"]),
        ]:
            candidates = [a for a in tier_assets if a["asset_type"] == asset_type]

            if candidates:
                logger.info(
                    f"Using {tier_name} assets as examples",
                    count=len(candidates),
                    asset_type=asset_type,
                )

                # Calculate similarity
                low_embedding = (await generate_embeddings([low_asset_text]))[0]
                candidate_texts = [c["text"] for c in candidates]
                candidate_embeddings = await generate_embeddings(candidate_texts)

                similarities = []
                for idx, cand_emb in enumerate(candidate_embeddings):
                    similarity = np.dot(low_embedding, cand_emb) / (
                        np.linalg.norm(low_embedding) * np.linalg.norm(cand_emb)
                    )
                    similarities.append(
                        {"asset": candidates[idx], "similarity": float(similarity)}
                    )

                similarities.sort(key=lambda x: x["similarity"], reverse=True)
                return similarities[:3], tier_name

        # No examples found - check campaign context
        keywords = self._extract_keywords(campaign_name, ad_group_name)
        if keywords:
            logger.warning(
                "No example assets - using campaign context", keywords=keywords
            )
            return [], "campaign_context"

        # Last resort
        logger.warning("No examples and no context - using LLM best practices")
        return [], "general_best_practices"

    def _extract_keywords(self, campaign_name: str, ad_group_name: str) -> list:
        text = f"{campaign_name} {ad_group_name}".lower()
        words = re.findall(r"\b[a-z]+\b", text)

        stopwords = {
            "campaign",
            "ad",
            "group",
            "adgroup",
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
        }

        keywords = [w for w in words if w not in stopwords and len(w) > 2]
        return keywords[:5]

    async def _generate_suggestions(
        self,
        low_asset: dict,
        similar_assets: list,
        source_tier: str,
        campaign_name: str,
        ad_group_name: str,
    ) -> list:
        asset_type = (
            "HEADLINE" if low_asset["asset_type"] == "HEADLINE" else "DESCRIPTION"
        )

        # Build examples text based on source tier
        if similar_assets:
            examples_text = "\n".join(
                [
                    f'- "{item["asset"]["text"]}" '
                    f"({item['asset']['label']}, {item['asset']['impressions']} impressions, "
                    f"similarity: {item['similarity']:.2f})"
                    for item in similar_assets
                ]
            )
            context_note = f"Learn from these {source_tier} examples:"

        elif source_tier == "campaign_context":
            keywords = self._extract_keywords(campaign_name, ad_group_name)
            examples_text = (
                "NO EXAMPLE ASSETS AVAILABLE.\n"
                f"Generate based on campaign context:\n"
                f"- Campaign: {campaign_name}\n"
                f"- Ad Group: {ad_group_name}\n"
                f"- Keywords to use: {', '.join(keywords)}\n\n"
                f"Create compelling {asset_type.lower()}s incorporating these keywords naturally."
            )
            context_note = "Campaign context:"

        else:
            examples_text = (
                "NO CAMPAIGN CONTEXT AVAILABLE.\n"
                f"Generate general best-practice {asset_type.lower()}s that:\n"
                f"- Are action-oriented and compelling\n"
                f"- Have broad appeal\n"
                f"- Follow Google Ads best practices\n"
                f"- Are clear and concise"
            )
            context_note = "General best practices:"

        prompt = prompt_loader.format_prompt(
            "asset_optimization_prompt.txt",
            count=5,  # Generate 5 options, pick best 1 after validation
            asset_type=asset_type,
            campaign_name=campaign_name,
            ad_group_name=ad_group_name,
            current_text=low_asset.get("text", ""),
            examples=examples_text,
            context_note=context_note,
        )

        response = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4o-mini",
            temperature=0.8,
        )

        raw_output = response.choices[0].message.content.strip()
        suggestions = safe_json_parse(raw_output)

        return suggestions if isinstance(suggestions, list) else []

    def _validate_suggestions(self, suggestions: list, asset_type: str) -> list:
        max_length = 30 if asset_type == "HEADLINE" else 90

        valid = []
        seen = set()

        for suggestion in suggestions:
            if not isinstance(suggestion, str):
                continue

            # Check length
            if len(suggestion) > max_length:
                logger.warning(
                    "Rejected suggestion (too long)",
                    text=suggestion,
                    length=len(suggestion),
                    max=max_length,
                )
                continue

            # Check duplicates
            normalized = suggestion.lower().strip()
            if normalized in seen:
                continue

            seen.add(normalized)
            valid.append({"text": suggestion, "character_count": len(suggestion)})

        return valid  # Return all valid, we'll pick best 1 in analyze_campaign
