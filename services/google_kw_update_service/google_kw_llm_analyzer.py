from typing import List, Dict, Union, Any
import json
import structlog
from utils import prompt_loader
from services.openai_client import chat_completion
from third_party.google.models.keyword_model import Keyword
from services.google_kw_update_service.google_kw_scorer import MultiFactorKeywordScorer
from services.google_kw_update_service import config
from exceptions.custom_exceptions import AIProcessingException

logger = structlog.get_logger(__name__)


class LLMKeywordAnalyzer:
    def __init__(self, keyword_scorer: MultiFactorKeywordScorer):
        self.keyword_scorer = keyword_scorer

    async def analyze_and_select_keywords(
        self,
        suggestion_keywords: List[Dict],
        anchor_keywords: List[Keyword],
        existing_keywords: List[Keyword],
        business_context: Dict,
    ) -> List[Dict]:
        """Analyze keyword suggestions with LLM and finalize with scoring."""
        logger.info("Starting LLM analysis", suggestion_count=len(suggestion_keywords))

        llm_selected_keywords = await self._perform_llm_keyword_selection(
            suggestion_keywords,
            anchor_keywords,
            existing_keywords,
            business_context,
        )

        if not llm_selected_keywords:
            logger.warning("No keywords selected by LLM")
            return []

        suggestions_lookup = {
            (s.keyword if hasattr(s, "keyword") else s.get("keyword", "")).lower(): s
            for s in suggestion_keywords
        }

        return self._finalize_keyword_suggestions(
            llm_selected_keywords, suggestions_lookup, existing_keywords
        )

    async def _perform_llm_keyword_selection(
        self,
        suggestion_keywords: List[Dict],
        anchor_keywords: List[Keyword],
        existing_keywords: List[Keyword],
        business_context: Dict,
    ) -> List[Dict]:
        """Perform LLM-based keyword selection using provided context."""
        logger.info(
            f"Performing LLM analysis on {len(suggestion_keywords)} suggestions"
        )

        llm_context = self._prepare_llm_context_data(
            suggestion_keywords, anchor_keywords, existing_keywords
        )

        prompt = prompt_loader.format_prompt(
            "keyword_update_service_prompt.txt",
            brand_info=business_context.get("brand_info"),
            unique_features=business_context.get("unique_features", []),
            anchor_summary=llm_context["anchor_summary"],
            existing_keywords=llm_context["existing_keywords"],
            suggestions_list=llm_context["formatted_suggestions"],
            suggestions_count=len(suggestion_keywords),
            url=business_context.get("url", "Not provided"),
            business_summary=business_context.get("summary", "Not provided"),
        )

        try:
            response = await chat_completion(
                model=config.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=config.LLM_TEMPERATURE,
                max_tokens=config.LLM_MAX_TOKENS,
                response_format={"type": "json_object"},
            )

            response_data = json.loads(response.choices[0].message.content.strip())

            selected_keywords = (
                response_data.get("keywords")
                or response_data.get("selected_keywords")
                or next((v for v in response_data.values() if isinstance(v, list)), [])
                if isinstance(response_data, dict)
                else (response_data if isinstance(response_data, list) else [])
            )

            logger.info(
                f"LLM selected {len(selected_keywords)} keywords from {len(suggestion_keywords)} suggestions"
            )
            return selected_keywords

        except (json.JSONDecodeError, Exception) as e:
            logger.exception(f"LLM keyword selection failed: {e}")
            raise AIProcessingException(
                message=f"LLM keyword selection failed: {str(e)}"
            )

    def _prepare_llm_context_data(
        self,
        suggestion_keywords: List[Dict],
        anchor_keywords: List[Keyword],
        existing_keywords: List[Keyword],
    ) -> Dict[str, str]:
        """Prepare context data for LLM prompt formatting."""
        logger.info("Preparing LLM context data for keyword selection")
        # Format suggestions with metrics
        formatted_suggestions = "\n".join(
            [
                f'{i + 1}. "{s.keyword if hasattr(s, "keyword") else s.get("keyword")}" - '
                f"Vol: {s.volume if hasattr(s, 'volume') else s.get('volume'):,}, "
                f"Comp: {s.competition if hasattr(s, 'competition') else s.get('competition')}, "
                f"CompIdx: {s.competitionIndex if hasattr(s, 'competitionIndex') else s.get('competitionIndex'):.2f}, "
                f"ROI: {s.roi_score if hasattr(s, 'roi_score') else s.get('roi_score', 0):.0f}, "
                f"Semantic: {s.semantic_score if hasattr(s, 'semantic_score') else s.get('semantic_score', 50):.0f}"
                for i, s in enumerate(suggestion_keywords)
            ]
        )

        # Calculate match type distribution from anchor keywords
        match_type_counts = {}
        for keyword in anchor_keywords:
            match_type_counts[keyword.match_type] = (
                match_type_counts.get(keyword.match_type, 0) + 1
            )

        # Format match types by frequency (most common first)
        sorted_match_types = sorted(
            match_type_counts.items(), key=lambda x: x[1], reverse=True
        )
        anchor_summary = f"Anchor keyword match types: {', '.join(f'{match_type}: {count}' for match_type, count in sorted_match_types)}"

        # Format existing keywords (limit to 50 to avoid token bloat)
        existing_keyword_texts = ", ".join(
            [kw.keyword for kw in existing_keywords[:50]]
        )
        if len(existing_keywords) > 50:
            existing_keyword_texts += f" ... and {len(existing_keywords) - 50} more"

        # Create set of existing keyword texts for fast case-insensitive lookup
        existing_keyword_set = {kw.keyword.lower() for kw in existing_keywords}

        return {
            "formatted_suggestions": formatted_suggestions,
            "anchor_summary": anchor_summary,
            "existing_keywords": existing_keyword_texts,
            "existing_keyword_set": existing_keyword_set,  # Pass set for later use
        }

    def _finalize_keyword_suggestions(
        self,
        llm_selected_keywords: List[Dict],
        google_suggestions_lookup: Dict[str, Union[Dict, Any]],
        existing_keywords: List[Keyword],
    ) -> List[Dict]:
        """Finalize keyword suggestions with deduplication and scoring."""
        logger.info("Finalizing keyword suggestions with deduplication and scoring")

        # Create set of existing keyword texts for fast lookup
        existing_keyword_set = {kw.keyword.lower() for kw in existing_keywords}

        # Create lookup map for suggestions (handling both objects and dicts)
        suggestions_lookup = {}
        # google_suggestions_lookup might be a list or a dict values depending on caller?
        # The caller passes `suggestions_lookup` which is a Dict[str, Dict/Obj]

        for s in google_suggestions_lookup.values():
            kw_text = (
                s.keyword if hasattr(s, "keyword") else s.get("keyword", "")
            ).lower()
            suggestions_lookup[kw_text] = s

        deduplicated_keywords = []
        duplicate_count = 0

        for selected_keyword in llm_selected_keywords:
            keyword_text = selected_keyword.get("keyword", "").strip().lower()

            if not keyword_text:
                continue

            # Skip duplicates (Case-insensitive)
            if keyword_text in existing_keyword_set:
                duplicate_count += 1
                continue

            # Merge with Google metrics
            google_kw = suggestions_lookup.get(keyword_text)
            if not google_kw:
                logger.warning(
                    f"Keyword '{keyword_text}' not in candidate list, skipping hallucination"
                )
                continue

            # Combine LLM selection with Google metrics data
            # If google_kw is a Pydantic model, dump it to dict first
            google_data = (
                google_kw.model_dump()
                if hasattr(google_kw, "model_dump")
                else (google_kw.dict() if hasattr(google_kw, "dict") else google_kw)
            )

            merged_keyword = {**selected_keyword, **google_data}
            deduplicated_keywords.append(merged_keyword)
        logger.info(
            f"Deduplicated keywords: {len(deduplicated_keywords)} selected, {duplicate_count} duplicates skipped"
        )
        # Calculate final scores
        scored_suggestions = self.keyword_scorer.calculate_keyword_scores(
            deduplicated_keywords
        )
        logger.info(f"Generated {len(scored_suggestions)} final scored suggestions")

        return scored_suggestions
