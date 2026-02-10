import json

from structlog import get_logger

from adapters.google.optimization.keyword_planner import GoogleKeywordPlannerAdapter
from core.models.optimization import KeywordRecommendation
from core.services.keyword_seed_expander import KeywordSeedExpander
from core.services.keyword_scorer import (
    calculate_semantic_scores,
    score_and_rank_keywords,
)
from services.openai_client import chat_completion
from models.business_model import BusinessMetadata
from utils.prompt_loader import load_prompt

logger = get_logger(__name__)


class KeywordIdeaService:
    def __init__(self):
        self.seed_expander = KeywordSeedExpander()
        self.keyword_planner = GoogleKeywordPlannerAdapter()

    async def suggest_keywords(
        self,
        campaign_details: dict,
        account_id: str,
        parent_id: str,
    ) -> list[KeywordRecommendation]:
        """Seed expand -> planner -> semantic score -> LLM select -> deduplicate."""
        keywords = campaign_details["entries"]
        good_kws = [e["keyword"] for e in keywords if e["strength"] in ("good", "top")]
        if not good_kws:
            return []

        top_kws = [e["keyword"] for e in keywords if e["strength"] == "top"]
        brand_info = campaign_details.get("brand_info") or BusinessMetadata()

        expanded_seeds = await self.seed_expander.expand_seeds(
            good_keywords=good_kws,
            business_type=brand_info.business_type,
            primary_location=brand_info.primary_location,
            features_context=", ".join(campaign_details.get("unique_features", [])),
        )

        google_suggestions = await self.keyword_planner.generate_keyword_ideas(
            customer_id=account_id,
            login_customer_id=parent_id,
            seed_keywords=expanded_seeds,
            url=campaign_details.get("business_url"),
        )
        if not google_suggestions:
            return []

        semantic_scores = await calculate_semantic_scores(
            [s["keyword"] for s in google_suggestions],
            top_kws or good_kws[:20],
        )
        for s in google_suggestions:
            s["semantic_score"] = semantic_scores.get(s["keyword"].lower(), 50.0)

        llm_selected = await self._llm_select_keywords(
            google_suggestions, campaign_details
        )
        if not llm_selected:
            return []

        return self._build_recommendations(
            llm_selected,
            google_suggestions,
            existing_kws={e["keyword"].lower() for e in keywords},
        )

    def _build_recommendations(
        self,
        llm_selected: list[dict],
        google_suggestions: list[dict],
        existing_kws: set[str],
    ) -> list[KeywordRecommendation]:
        suggestion_map = {s["keyword"].lower(): s for s in google_suggestions}
        finalized = []
        for kw in llm_selected:
            text = kw.get("keyword", "").strip().lower()
            google_data = suggestion_map.get(text)
            if not text or text in existing_kws or not google_data:
                continue
            finalized.append({**kw, **google_data})

        return [
            KeywordRecommendation(
                text=kw["keyword"],
                match_type=kw.get("match_type", "PHRASE"),
                reason=kw.get("reason", "High-potential keyword from Keyword Planner"),
                origin="KEYWORD",
                metrics={
                    "volume": kw.get("volume", 0),
                    "competition": kw.get("competition", ""),
                    "competitionIndex": kw.get("competitionIndex", 0),
                    "semantic_score": kw.get("semantic_score", 0),
                },
                score=kw.get("final_score"),
            )
            for kw in score_and_rank_keywords(finalized)[:15]
        ]

    async def _llm_select_keywords(
        self,
        suggestions: list[dict],
        campaign_details: dict,
    ) -> list[dict]:
        """Ask LLM to select best keywords from candidates for this campaign."""
        prompt = self._format_selection_prompt(suggestions, campaign_details)

        response = await chat_completion(
            messages=[
                {"role": "system", "content": "You are a Google Ads keyword analyst."},
                {"role": "user", "content": prompt},
            ],
            model="gpt-4o-mini",
            temperature=0.3,
            max_tokens=6000,
            response_format={"type": "json_object"},
        )

        parsed = json.loads(response.choices[0].message.content.strip())
        selected = parsed.get("keywords") or parsed.get("selected_keywords") or []
        return selected if isinstance(selected, list) else []

    def _format_selection_prompt(
        self, suggestions: list[dict], campaign_details: dict
    ) -> str:
        brand_info = campaign_details.get("brand_info") or BusinessMetadata()
        entries = campaign_details["entries"]

        match_types: dict[str, int] = {}
        for entry in entries:
            mt = entry.get("match_type", "phrase")
            match_types[mt] = match_types.get(mt, 0) + 1

        return load_prompt("optimization/keyword_suggestion_prompt.txt").format(
            brand_name=brand_info.brand_name,
            business_type=brand_info.business_type,
            service_areas=", ".join(brand_info.service_areas)
            if brand_info.service_areas
            else "N/A",
            url=campaign_details.get("business_url", ""),
            unique_features=", ".join(campaign_details.get("unique_features", [])),
            business_summary=campaign_details.get("business_summary", ""),
            campaign_name=campaign_details.get("name", ""),
            existing_keywords=", ".join(e["keyword"] for e in entries[:50]),
            suggestions_count=min(len(suggestions), 50),
            suggestions_list="\n".join(
                f"- {s['keyword']} | Vol: {s.get('volume', 0)} | Comp: {s.get('competition', 'UNKNOWN')} "
                f"| CompIdx: {s.get('competitionIndex', 0):.2f} | Semantic: {s.get('semantic_score', 50):.0f}"
                for s in suggestions[:50]
            ),
            anchor_summary=", ".join(
                f"{mt}: {c}"
                for mt, c in sorted(match_types.items(), key=lambda x: -x[1])
            ),
        )
