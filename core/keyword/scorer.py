import asyncio
from math import inf

import numpy as np
from structlog import get_logger

from services.openai_client import generate_embeddings

logger = get_logger(__name__)

SCORE_WEIGHTS = {
    "volume": 0.25,
    "competition": 0.20,
    "business_relevance": 0.25,
    "intent": 0.15,
    "semantic": 0.15,
}
VOLUME_SCORE_TIERS = [
    (0, 100, 20),
    (100, 500, 40),
    (500, 1000, 60),
    (1000, 5000, 80),
    (5000, inf, 100),
]
BUSINESS_RELEVANCE_SCORES = {"high": 100, "medium": 60, "low": 20}
INTENT_TYPE_SCORES = {
    "transactional": 100,
    "commercial": 80,
    "navigational": 60,
    "informational": 40,
    "unknown": 20,
}
CROSS_BUSINESS_PENALTY = 0.5
MINIMUM_SCORE = 40


async def calculate_semantic_scores(
    suggestion_texts: list[str], anchor_texts: list[str]
) -> dict[str, float]:
    """Compute max cosine similarity of each suggestion against all anchors."""
    if not suggestion_texts or not anchor_texts:
        return {}
    try:
        anchor_embeddings, suggestion_embeddings = await asyncio.gather(
            generate_embeddings(anchor_texts),
            generate_embeddings(suggestion_texts),
        )
        anchor_np = np.array(anchor_embeddings)
        suggestion_np = np.array(suggestion_embeddings)
        similarity_matrix = np.dot(suggestion_np, anchor_np.T)
        max_similarities = similarity_matrix.max(axis=1)
        return {
            kw.lower(): round(float(max_similarities[i]) * 100, 2)
            for i, kw in enumerate(suggestion_texts)
        }
    except Exception:
        logger.error(
            "semantic_scoring_failed",
            exc_info=True,
            suggestion_texts=suggestion_texts,
            anchor_texts=anchor_texts,
        )
        return {}


def score_and_rank_keywords(keywords: list[dict]) -> list[dict]:
    """Score, filter below MINIMUM_SCORE, and sort descending by final_score."""
    scored = []
    for kw in keywords:
        result = _score_single_keyword(kw)
        if result is not None:
            scored.append(result)
    scored.sort(key=lambda k: k["final_score"], reverse=True)
    return scored


def _score_single_keyword(kw: dict) -> dict | None:
    volume_score = _volume_score(kw.get("volume", 0))
    competition_score = (1 - kw.get("competitionIndex", 0.5)) * 100
    business_score = BUSINESS_RELEVANCE_SCORES.get(
        kw.get("business_relevance", "medium"), 60
    )
    intent_score = INTENT_TYPE_SCORES.get(kw.get("intent", "unknown"), 20)
    semantic_score = kw.get("semantic_score", 50.0)

    final = (
        volume_score * SCORE_WEIGHTS["volume"]
        + competition_score * SCORE_WEIGHTS["competition"]
        + business_score * SCORE_WEIGHTS["business_relevance"]
        + intent_score * SCORE_WEIGHTS["intent"]
        + semantic_score * SCORE_WEIGHTS["semantic"]
    )

    if kw.get("is_cross_business"):
        final *= CROSS_BUSINESS_PENALTY

    if final < MINIMUM_SCORE:
        return None

    return {
        **kw,
        "final_score": round(final, 2),
        "score_breakdown": {
            "volume": round(volume_score, 2),
            "competition": round(competition_score, 2),
            "business_relevance": round(business_score, 2),
            "intent": round(intent_score, 2),
            "semantic": round(semantic_score, 2),
        },
    }


def _volume_score(volume: int) -> float:
    for low, high, score in VOLUME_SCORE_TIERS:
        if low <= volume < high:
            return score
    return 20.0
