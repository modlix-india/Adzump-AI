import asyncio
import os
import pytest
from unittest.mock import AsyncMock, patch

from services.generation.platform_config import get_platform_config
from services.generation.ad_text_service import AdTextService
from services.generation.ad_text_utils import (
    deduplicate_items,
    filter_by_length,
    rescue_pool_fallback,
)
from core.models.shared import AgeTargeting, GenderTargeting


# ── Platform Config ───────────────────────────────────────────────────────────


class TestPlatformConfig:
    def test_google_config_loads(self):
        cfg = get_platform_config("google")
        assert cfg.llm_model == "gpt-4o-mini"
        assert cfg.max_retries == 3

    def test_meta_config_loads(self):
        cfg = get_platform_config("meta")
        assert cfg.llm_model == "gpt-4o-mini"
        assert cfg.age_output_format == "min_max"

    def test_unsupported_platform_raises(self):
        with pytest.raises(ValueError, match="Unsupported platform 'tiktok'"):
            get_platform_config("tiktok")

    def test_empty_platform_raises(self):
        with pytest.raises(ValueError):
            get_platform_config("")


# ── Content Type Config ───────────────────────────────────────────────────────


class TestContentTypeConfig:
    def test_google_has_headlines_and_descriptions(self):
        cfg = get_platform_config("google")
        assert "headlines" in cfg.content_types
        assert "descriptions" in cfg.content_types

    def test_google_does_not_have_primary_text(self):
        cfg = get_platform_config("google")
        with pytest.raises(ValueError, match="primary_text"):
            cfg.get_content_type("primary_text")

    def test_meta_has_all_three_content_types(self):
        cfg = get_platform_config("meta")
        assert "headlines" in cfg.content_types
        assert "descriptions" in cfg.content_types
        assert "primary_text" in cfg.content_types

    def test_google_headlines_requires_keywords(self):
        assert (
            get_platform_config("google")
            .get_content_type("headlines")
            .requires_keywords
            is True
        )

    def test_google_descriptions_requires_keywords(self):
        assert (
            get_platform_config("google")
            .get_content_type("descriptions")
            .requires_keywords
            is True
        )

    def test_meta_headlines_does_not_require_keywords(self):
        assert (
            get_platform_config("meta").get_content_type("headlines").requires_keywords
            is False
        )

    def test_meta_primary_text_does_not_require_keywords(self):
        assert (
            get_platform_config("meta")
            .get_content_type("primary_text")
            .requires_keywords
            is False
        )

    def test_google_headline_char_limits(self):
        ct = get_platform_config("google").get_content_type("headlines")
        assert ct.min_chars == 20
        assert ct.max_chars == 30

    def test_meta_primary_text_char_limits(self):
        ct = get_platform_config("meta").get_content_type("primary_text")
        assert ct.min_chars == 60
        assert ct.max_chars == 125

    def test_prompts_point_to_correct_files(self):
        base = os.path.join(os.path.dirname(__file__), "../../prompts")
        for platform in ["google", "meta"]:
            cfg = get_platform_config(platform)
            for ct_name, ct in cfg.content_types.items():
                full_path = os.path.normpath(os.path.join(base, ct.prompt))
                assert os.path.exists(full_path), f"Prompt file missing: {ct.prompt}"


# ── AdTextService Validation ──────────────────────────────────────────────────


class TestAdTextServiceValidation:
    def test_google_headlines_without_keywords_raises(self):
        svc = AdTextService()
        with pytest.raises(ValueError, match="requires keywords"):
            asyncio.run(
                svc.generate(
                    summary="test", platform="google", content_type="headlines"
                )
            )

    def test_google_descriptions_without_keywords_raises(self):
        svc = AdTextService()
        with pytest.raises(ValueError, match="requires keywords"):
            asyncio.run(
                svc.generate(
                    summary="test", platform="google", content_type="descriptions"
                )
            )

    def test_meta_headlines_without_keywords_does_not_raise_immediately(self):
        svc = AdTextService()
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = '["Great headline here"]'
        mock_response.usage = None
        with patch(
            "services.generation.ad_text_service.chat_completion",
            return_value=mock_response,
        ):
            result = asyncio.run(
                svc.generate(summary="test", platform="meta", content_type="headlines")
            )
        assert isinstance(result, list)

    def test_unsupported_platform_raises_in_service(self):
        svc = AdTextService()
        with pytest.raises(ValueError):
            asyncio.run(
                svc.generate(
                    summary="test", platform="snapchat", content_type="headlines"
                )
            )

    def test_unsupported_content_type_raises_in_service(self):
        svc = AdTextService()
        with pytest.raises(ValueError):
            asyncio.run(
                svc.generate(summary="test", platform="meta", content_type="tagline")
            )


# ── AdTextService with Mocked LLM ────────────────────────────────────────────


class TestAdTextServiceMocked:
    def _make_mock_response(self, content: str):
        mock = AsyncMock()
        mock.choices = [AsyncMock()]
        mock.choices[0].message.content = content
        mock.usage = None
        return mock

    def test_returns_list_of_strings(self):
        svc = AdTextService()
        mock_resp = self._make_mock_response('["Short headline", "Another one here"]')
        with patch(
            "services.generation.ad_text_service.chat_completion",
            return_value=mock_resp,
        ):
            result = asyncio.run(
                svc.generate(summary="test", platform="meta", content_type="headlines")
            )
        assert isinstance(result, list)
        assert all(isinstance(h, str) for h in result)

    def test_dedup_removes_similar_items(self):
        items = ["Best Apartments Now", "Best Apartments Now", "Best Apartment Here"]
        result = deduplicate_items(items, similarity_threshold=0.9)
        assert len(result) < len(items)
        assert "Best Apartments Now" in result

    def test_dedup_exact_case_insensitive(self):
        items = ["Luxury Homes", "luxury homes", "LUXURY HOMES"]
        result = deduplicate_items(items, similarity_threshold=1.0)
        assert len(result) == 1

    def test_dedup_keeps_distinct_items(self):
        items = ["Luxury Homes", "Budget Flights", "Best Schools"]
        result = deduplicate_items(items, similarity_threshold=0.8)
        assert len(result) == 3

    def test_filter_by_length_keeps_in_range(self):
        items = [
            "Hi",
            "Good headline here",
            "This is a very long headline that should be removed",
        ]
        result = filter_by_length(items, min_chars=10, max_chars=25)
        assert "Good headline here" in result
        assert "Hi" not in result
        assert "This is a very long headline that should be removed" not in result

    def test_filter_by_length_empty_input(self):
        assert filter_by_length([], 10, 30) == []

    def test_rescue_pool_returns_best_items(self):
        items = ["x"] * 5 + ["A good headline"] + ["y"] * 3
        result = rescue_pool_fallback(
            all_items=items,
            min_chars=10,
            max_chars=30,
            similarity_threshold=0.8,
            min_count=1,
        )
        assert "A good headline" in result

    def test_rescue_pool_uses_relaxed_bounds(self):
        item = "A" * 91  # just outside max_chars=90, within 10% relaxation
        result = rescue_pool_fallback(
            all_items=[item],
            min_chars=75,
            max_chars=90,
            similarity_threshold=0.8,
            min_count=1,
        )
        assert item in result


# ── Shared Models ─────────────────────────────────────────────────────────────


class TestSharedModels:
    def test_age_targeting_meta_shape(self):
        age = AgeTargeting(age_min=25, age_max=44)
        assert age.age_min == 25
        assert age.age_max == 44
        assert age.age_ranges == []

    def test_age_targeting_google_shape(self):
        age = AgeTargeting(age_ranges=["AGE_RANGE_25_34", "AGE_RANGE_35_44"])
        assert age.age_min is None
        assert age.age_max is None
        assert len(age.age_ranges) == 2

    def test_age_targeting_defaults(self):
        age = AgeTargeting()
        assert age.age_min is None
        assert age.age_max is None
        assert age.age_ranges == []

    def test_gender_targeting_shape(self):
        gender = GenderTargeting(genders=["MALE", "FEMALE"])
        assert "MALE" in gender.genders
        assert "FEMALE" in gender.genders

    def test_gender_targeting_empty(self):
        assert GenderTargeting(genders=[]).genders == []
