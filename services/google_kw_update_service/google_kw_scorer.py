from typing import List, Dict
import structlog
import numpy as np
from services.openai_client import generate_embeddings
from third_party.google.models.keyword_model import Keyword
from services.google_kw_update_service import config
from exceptions.custom_exceptions import AIProcessingException

logger = structlog.get_logger(__name__)


class SemanticSimilarityScorer:
    """Calculates semantic similarity scores between keyword suggestions and top performers."""

    async def calculate_semantic_similarity_scores(
        self, suggestion_keywords: List[Dict], anchor_keywords: List[Keyword]
    ) -> Dict[str, float]:
        """Calculate semantic similarity scores for suggestions using anchor keywords."""
        logger.info("Calculating semantic similarity scores...")

        if not suggestion_keywords or not anchor_keywords:
            logger.warning("Empty suggestions or anchor keywords list")
            return {}

        try:
            # Extract keyword texts
            anchor_texts = [kw.keyword for kw in anchor_keywords]
            suggestion_texts = [
                s.keyword if hasattr(s, "keyword") else s.get("keyword", "")
                for s in suggestion_keywords
            ]

            logger.info(
                "Generating embeddings",
                anchor_count=len(anchor_texts),
                suggestion_count=len(suggestion_texts),
            )

            # Generate embeddings
            # Note: OpenAI embeddings are normalized to length 1, so dot product == cosine similarity
            anchor_embeddings = np.array(await generate_embeddings(anchor_texts))
            suggestion_embeddings = np.array(
                await generate_embeddings(suggestion_texts)
            )

            # Calculate cosine similarities (dot product since normalized)
            # Shape: (num_suggestions, num_anchor_keywords)
            similarity_matrix = np.dot(suggestion_embeddings, anchor_embeddings.T)

            # Get max similarity for each suggestion
            max_similarities = similarity_matrix.max(axis=1)

            # Create score dictionary (scaled to 0-100)
            semantic_scores = {
                text.lower(): round(float(score) * 100, 1)
                for text, score in zip(suggestion_texts, max_similarities)
            }

            average_score = np.mean(max_similarities) * 100
            logger.info(
                f"Calculated semantic scores. Average score: {average_score:.2f}%"
            )

            return semantic_scores

        except Exception as e:
            logger.exception(f"Error calculating semantic similarity scores: {e}")
            raise AIProcessingException(
                message=f"Semantic similarity calculation failed: {str(e)}"
            )


class MultiFactorKeywordScorer:
    # Scores keywords using multiple weighted factors

    def calculate_keyword_scores(self, keywords: List[Dict]) -> List[Dict]:
        """Score, filter, and sort keyword candidates."""
        scored_keywords: List[Dict] = []

        for kw in keywords:
            scored_kw = self._score_single_keyword(kw)
            if scored_kw:
                scored_keywords.append(scored_kw)

        scored_keywords.sort(key=lambda x: x["final_score"], reverse=True)
        logger.info(
            "%d suggestions passed quality threshold of %s",
            len(scored_keywords),
            config.MINIMUM_ACCEPTABLE_SCORE,
        )
        return scored_keywords

    def _score_single_keyword(self, kw: Dict) -> Dict | None:
        """Calculates score for a single keyword candidate."""
        volume = kw.get("volume", 0)
        competition_index = kw.get("competitionIndex", 0.5)
        business_relevance = (kw.get("business_relevance") or "medium").lower()
        intent = (kw.get("intent") or "unknown").lower()
        semantic_score = kw.get("semantic_score", 50)

        # Component scores
        volume_score = self._volume_score(volume)
        competition_score = max(0, (1 - competition_index) * 100)
        business_score = config.BUSINESS_RELEVANCE_SCORES.get(business_relevance, 60)
        intent_score = config.INTENT_TYPE_SCORES.get(intent, 20)

        # Weighted composite
        composite = (
            volume_score * config.SCORE_WEIGHTS["volume"]
            + competition_score * config.SCORE_WEIGHTS["competition"]
            + business_score * config.SCORE_WEIGHTS["business_relevance"]
            + intent_score * config.SCORE_WEIGHTS["intent"]
            + semantic_score * config.SCORE_WEIGHTS["semantic"]
        )

        if kw.get("is_cross_business", False):
            composite *= config.CROSS_BUSINESS_PENALTY_MULTIPLIER

        if composite < config.MINIMUM_ACCEPTABLE_SCORE:
            return None

        return {
            "keyword": kw.get("keyword"),
            "match_type": kw.get("match_type", "PHRASE"),
            "final_score": round(composite, 2),
            "volume": volume,
            "competition": kw.get("competition"),
            "competitionIndex": competition_index,
            "intent": intent,
            "business_relevance": business_relevance,
            "semantic_relevance": semantic_score,
            "is_cross_business": kw.get("is_cross_business", False),
            "why_selected": kw.get("why_selected", "High potential keyword"),
            "score_breakdown": {
                "volume_score": round(volume_score, 1),
                "competition_score": round(competition_score, 1),
                "business_score": round(business_score, 1),
                "intent_score": round(intent_score, 1),
                "semantic_score": round(semantic_score, 1),
            },
        }

    def _volume_score(self, volume: int) -> float:
        """Map raw volume into a tier score."""
        for min_v, max_v, score in config.VOLUME_SCORE_TIERS:
            if min_v <= volume < max_v:
                return score
        return 20
