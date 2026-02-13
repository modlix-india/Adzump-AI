import re
from typing import Tuple
import numpy as np
import structlog
from services.openai_client import generate_embeddings

logger = structlog.get_logger(__name__)


class SimilarityMatcher:
    async def find_similar_assets(
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
        keywords = self.extract_keywords(campaign_name, ad_group_name)
        if keywords:
            logger.warning(
                "No example assets - using campaign context", keywords=keywords
            )
            return [], "campaign_context"

        # Last resort
        logger.warning("No examples and no context - using LLM best practices")
        return [], "general_best_practices"

    @staticmethod
    def extract_keywords(campaign_name: str, ad_group_name: str) -> list:
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
