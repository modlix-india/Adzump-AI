"""Keyword planner geo chain: curated > caller ids > country constant > India default."""
from services.google_keywords_service import GoogleKeywordService

resolve = GoogleKeywordService.resolve_keyword_location_ids


def test_curated_locations_win():
    campaign_data = {
        "googleMappedLocations": [
            {"name": "Juhu", "google": {"resourceName": "geoTargetConstants/1"}},
        ],
        "countryGeoConstant": "geoTargetConstants/2356",
    }
    assert resolve(campaign_data, ["geoTargetConstants/9"]) == ["geoTargetConstants/1"]


def test_caller_ids_beat_country_constant():
    campaign_data = {"countryGeoConstant": "geoTargetConstants/2356"}
    assert resolve(campaign_data, ["geoTargetConstants/9"]) == ["geoTargetConstants/9"]


def test_country_constant_beats_india_default():
    campaign_data = {"countryGeoConstant": "geoTargetConstants/2840"}
    assert resolve(campaign_data, None) == ["geoTargetConstants/2840"]


def test_india_default_last():
    assert resolve({}, None) == ["geoTargetConstants/2356"]


def test_keyless_curated_entries_skipped():
    campaign_data = {
        "googleMappedLocations": [{"name": "X", "google": {}}],
        "countryGeoConstant": "geoTargetConstants/2356",
    }
    assert resolve(campaign_data, None) == ["geoTargetConstants/2356"]
