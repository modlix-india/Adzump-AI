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


async def assign_ad_groups(
    new_keywords: list[str], existing_keywords: list[dict]
) -> dict[str, dict]:
    # TODO: remove after doing analysis on ad-group level so we don't need to find ad group for new keyword
    """Assign each suggestion to the ad group with highest embedding similarity."""
    ad_groups: dict[str, dict] = {}
    for e in existing_keywords:
        ag_id = e.get("ad_group_id", "")
        if ag_id not in ad_groups:
            ad_groups[ag_id] = {
                "ad_group_id": ag_id,
                "ad_group_name": e.get("ad_group_name", ""),
                "keywords": [],
            }
        ad_groups[ag_id]["keywords"].append(e["keyword"])

    if not ad_groups or not new_keywords:
        return {}

    if len(ad_groups) == 1:
        ag = next(iter(ad_groups.values()))
        return {
            t.lower(): {
                "ad_group_id": ag["ad_group_id"],
                "ad_group_name": ag["ad_group_name"],
            }
            for t in new_keywords
        }

    try:
        all_existing = [kw for ag in ad_groups.values() for kw in ag["keywords"]]
        new_emb, existing_emb = await asyncio.gather(
            generate_embeddings(new_keywords),
            generate_embeddings(all_existing),
        )
        sim_matrix = np.dot(np.array(new_emb), np.array(existing_emb).T)

        ag_ranges: dict[str, tuple[int, int]] = {}
        offset = 0
        for ag_id, ag_data in ad_groups.items():
            count = len(ag_data["keywords"])
            ag_ranges[ag_id] = (offset, offset + count)
            offset += count

        assignments: dict[str, dict] = {}
        for i, text in enumerate(new_keywords):
            best_id, best_score = "", -1.0
            for ag_id, (start, end) in ag_ranges.items():
                max_sim = float(sim_matrix[i, start:end].max())
                if max_sim > best_score:
                    best_score = max_sim
                    best_id = ag_id
            if best_id:
                ag = ad_groups[best_id]
                assignments[text.lower()] = {
                    "ad_group_id": ag["ad_group_id"],
                    "ad_group_name": ag["ad_group_name"],
                }
        return assignments
    except Exception:
        logger.warning("ad_group_assignment_failed", exc_info=True)
        return {}


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
