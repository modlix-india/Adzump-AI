import re
import logging
import json
from typing import List,Dict,Set
from utils.text_utils import normalize_text
from models.keyword_model import ( 
    KeywordSuggestion, 
    OptimizedKeyword,
    MatchType, 
    NegativeKeyword,
)

logger = logging.getLogger(__name__)
WORD_PATTERN = re.compile(r"\w+")

class KeywordUtils:
    
    @staticmethod
    def parse_and_normalize_seed_keywords(raw: str, limit: int) -> List[str]:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                keywords = parsed
            else:
                raise ValueError("Response not a list")
        except Exception:
            parts = re.findall(r'"([^"]+)"', raw)
            if not parts:
                parts = re.split(r'[\n,•;]+', raw)
            keywords = [p.strip().strip('"\'') for p in parts if p.strip()]
        
        return KeywordUtils.normalize_keywords(keywords, limit)
    
    @staticmethod
    def normalize_keywords(keywords: List[str], limit: int) -> List[str]:
        normalized, seen = [], set()
        for kw in keywords:
            if not isinstance(kw, str):
                continue
            k = normalize_text(kw)
            if 2 <= len(k) and k not in seen:
                normalized.append(k)
                seen.add(k)
        return normalized[:limit]

    @staticmethod
    def create_distributed_keywords(
        suggestions: List[KeywordSuggestion],
        rationale: str = "Distributed selection"
    ) -> List[OptimizedKeyword]:
        """Create keywords with 10/70/20 match type distribution.
            - 10% BROAD (first 10%)
            - 70% PHRASE (next 70%)
            - 20% EXACT (last 20%)
        """
        optimized_keywords = []
        total = len(suggestions)

        for i, suggestion in enumerate(suggestions):
            ratio = (i + 1) / total if total > 0 else 0
            
            if ratio <= 0.10:
                match_type = MatchType.BROAD
            elif ratio <= 0.80:
                match_type = MatchType.PHRASE
            else:
                match_type = MatchType.EXACT

            optimized = OptimizedKeyword(
                keyword=suggestion.keyword,
                volume=suggestion.volume,
                competition=suggestion.competition,
                competitionIndex=suggestion.competitionIndex,
                match_type=match_type,
                rationale=rationale,
                is_cross_business=False
            )
            optimized_keywords.append(optimized)

        return optimized_keywords
    
    @staticmethod
    def filter_and_validate_negatives(
        negatives_raw: List[Dict[str, str]],
        positive_keywords: List[OptimizedKeyword],
        safety_patterns: List[re.Pattern]
    ) -> List[NegativeKeyword]:
        """Filter and validate negative keywords."""
        from utils.text_utils import normalize_text
        
        cleaned_negatives: List[NegativeKeyword] = []
        seen_keywords: Set[str] = set()
        
        positive_keywords_lower = {kw.keyword.lower() for kw in positive_keywords}
        positive_tokens = set()
        for kw in positive_keywords_lower:
            positive_tokens.update(WORD_PATTERN.findall(kw))
        
        for item in negatives_raw:
            if not isinstance(item, dict) or 'keyword' not in item:
                continue
            
            kw = normalize_text(item.get("keyword", ""))
            reason = item.get("reason", "Budget protection")
            
            kw_len = len(kw)
            if not kw or kw_len < 2 or kw_len > 50 or kw in seen_keywords:
                continue
            
            if any(pattern.search(kw) for pattern in safety_patterns):
                continue
            
            kw_lower = kw.lower()
            if kw_lower in positive_keywords_lower:
                continue
            
            kw_tokens = set(WORD_PATTERN.findall(kw_lower))
            if kw_tokens:
                overlap_ratio = len(kw_tokens & positive_tokens) / len(kw_tokens)
                if overlap_ratio >= 0.8:
                    continue
            
            seen_keywords.add(kw)
            negative = NegativeKeyword(keyword=kw, reason=reason)
            cleaned_negatives.append(negative)

            if len(cleaned_negatives) >= 40:
                break
        
        return cleaned_negatives
