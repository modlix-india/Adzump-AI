from typing import List, Dict, Tuple
import logging
import numpy as np
from third_party.google.models.keyword_model import Keyword
from services.google_kw_update_service import config

logger = logging.getLogger(__name__)


class KeywordPerformanceClassifier:
    """
    Classifies keywords based on performance metrics.

    This class encapsulates all logic for:
    - Classifying keywords as good or poor performers
    - Identifying top performers using normalized scoring
    - Calculating performance scores across multiple dimensions
    """

    def classify_keywords_by_performance(
        self,
        keywords: List[Keyword]
    ) -> Tuple[List[Keyword], List[Dict]]:
        """Classify keywords into good and poor performers based on metrics."""
        good_keywords: List[Keyword] = []
        poor_keywords: List[Dict] = []

        # Separate keywords by impression count
        zero_impression_keywords = [
            kw for kw in keywords if kw.impressions == 0]
        keywords_with_data = [kw for kw in keywords if kw.impressions > 0]

        # Handle zero-impression keywords
        for keyword in zero_impression_keywords:
            keyword_dict = keyword.model_dump()
            keyword_dict['poor_reasons'] = [
                "No impressions - keyword not generating traffic"]
            poor_keywords.append(keyword_dict)

        logger.info(
            f"Added {len(zero_impression_keywords)} zero-impression keywords to poor list")

        if not keywords_with_data:
            logger.warning("No keywords with impressions to analyze")
            return good_keywords, poor_keywords

        # Calculate median CPL for comparison
        median_cpl = self._calculate_median_cpl(keywords_with_data)
        logger.info(
            f"Using median CPL: ₹{median_cpl:.2f} for {len(keywords_with_data)} keywords")

        # Classify each keyword with data
        for keyword in keywords_with_data:
            poor_performance_reasons = self._identify_poor_performance_reasons(
                keyword, median_cpl)

            if len(poor_performance_reasons) >= 2:
                keyword_dict = keyword.model_dump()
                keyword_dict['poor_reasons'] = poor_performance_reasons
                poor_keywords.append(keyword_dict)
            else:
                good_keywords.append(keyword)

        logger.info(
            f"Classification: {len(good_keywords)} good, {len(poor_keywords)} poor")
        return good_keywords, poor_keywords

    def extract_top_performers(
        self,
        good_keywords: List[Keyword],
        top_percentage: float = config.TOP_PERFORMER_PERCENTAGE
    ) -> List[Keyword]:
        """Extract top performing keywords using normalized scoring based on efficiency, volume, and conversions."""
        if not good_keywords:
            return []

        # Calculate normalization factors
        max_values = self._calculate_max_metric_values(good_keywords)
        min_cpl, max_cpl = self._calculate_cpl_range(good_keywords)

        # Score each keyword
        scored_keywords = [
            (keyword, self._calculate_normalized_keyword_score(
                keyword, max_values, min_cpl, max_cpl))
            for keyword in good_keywords
        ]

        # Sort by score and select top percentag
        scored_keywords.sort(key=lambda x: x[1], reverse=True)
        top_count = max(1, int(len(scored_keywords) * top_percentage))

        logger.info(
            f"Selected {top_count} top performers. Top score: {scored_keywords[0][1]:.1f}/100")
        return [keyword for keyword, _ in scored_keywords[:top_count]]

    def _calculate_median_cpl(self, keywords: List[Keyword]) -> float:
        """Calculate median CPL from keywords with valid CPL values."""
        valid_cpls = [
            kw.cpl for kw in keywords if kw.cpl is not None and kw.cpl > 0]
        return sorted(valid_cpls)[len(valid_cpls) // 2] if valid_cpls else config.DEFAULT_MAX_CPL

    def _identify_poor_performance_reasons(self, keyword: Keyword, median_cpl: float) -> List[str]:
        """Identify reasons why a keyword is performing poorly based on multiple indicators."""
        reasons = []

        # Check CTR
        if keyword.ctr < config.CTR_THRESHOLD:
            reasons.append(f"Low CTR ({keyword.ctr:.1f}%)")

        # Check quality score
        if keyword.quality_score and keyword.quality_score <= config.QUALITY_SCORE_THRESHOLD:
            reasons.append(f"Low quality score ({keyword.quality_score})")

        # Check conversions
        if keyword.conversions == 0 and keyword.clicks >= config.MIN_CLICKS_FOR_CONVERSIONS:
            reasons.append("No conversions despite clicks")

        # Check CPL (only if not already flagged for no conversions)
        elif keyword.cpl and keyword.cpl > median_cpl * config.CPL_MULTIPLIER:
            reasons.append(
                f"High CPL (₹{keyword.cpl:.2f} vs ₹{median_cpl:.2f} median)")

        # Check conversion rate
        if keyword.conv_rate < 1.0 and keyword.clicks >= config.MIN_CLICKS_FOR_CONVERSIONS:
            reasons.append(f"Low conversion rate ({keyword.conv_rate:.1f}%)")

        return reasons

    def _calculate_max_metric_values(self, keywords: List[Keyword]) -> Dict[str, float]:
        """Calculate maximum values for each metric for normalization."""
        quality_scores = [
            kw.quality_score for kw in keywords if kw.quality_score]

        return {
            'impressions': max([kw.impressions for kw in keywords]) or 1,
            'ctr': max([kw.ctr for kw in keywords]) or 1,
            'quality': max(quality_scores) if quality_scores else 10,
            'conversions': max([kw.conversions for kw in keywords]) or 1
        }

    def _calculate_cpl_range(self, keywords: List[Keyword]) -> Tuple[float, float]:
        """Calculate CPL range (min, max) for normalization."""
        valid_cpls = [kw.cpl for kw in keywords if kw.cpl and kw.cpl > 0]

        if valid_cpls:
            min_cpl = min(valid_cpls)
            max_cpl = min(max(valid_cpls), config.DEFAULT_MAX_CPL * 2)
            logger.info(f"CPL range: ₹{min_cpl:.2f} to ₹{max_cpl:.2f}")
        else:
            min_cpl = config.DEFAULT_MIN_CPL
            max_cpl = config.DEFAULT_MAX_CPL
            logger.warning(
                f"No CPL data, using default range: ₹{min_cpl} to ₹{max_cpl}")

        return min_cpl, max_cpl

    def _calculate_normalized_keyword_score(
        self,
        keyword: Keyword,
        max_values: Dict[str, float],
        min_cpl: float,
        max_cpl: float
    ) -> float:
        """Calculate normalized performance score combining efficiency, volume, and conversion metrics."""
        # Normalize individual metrics to 0-100 scale
        impression_score = (keyword.impressions /
                            max_values['impressions']) * 100
        ctr_score = (keyword.ctr / max_values['ctr']) * 100
        quality_score = (keyword.quality_score /
                         max_values['quality'] * 100) if keyword.quality_score else 50

        # CPL score (inversely normalized - lower CPL is better)
        if keyword.cpl and keyword.cpl > 0:
            cpl_value = min(keyword.cpl, max_cpl)
            cpl_normalized = (cpl_value - min_cpl) / \
                (max_cpl - min_cpl) if max_cpl > min_cpl else 0
            cpl_score = (1 - cpl_normalized) * 100
        else:
            cpl_score = 50  # Neutral score if no CPL data

        conversion_score = (keyword.conversions /
                            max_values['conversions']) * 100

        # Calculate weighted final score
        efficiency_score = (ctr_score + quality_score + cpl_score) / 3
        final_score = (efficiency_score * 0.40 +
                       impression_score * 0.30 + conversion_score * 0.30)

        return final_score
