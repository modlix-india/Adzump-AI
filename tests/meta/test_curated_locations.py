"""curated_meta_locations — adzump's user-curated locations → adset geo input.

The adzump bridge fills campaign_data["metaMappedLocations"] with entries
carrying a NESTED platform handle ({..., meta: {type, key, name}} — producer:
nocode-ai agents/location). The helper turns them into build_geo_structure-
ready {key, name, type} dicts so the adset agent can prefer the user's picks
over search re-resolution.
"""
import pytest

from adapters.meta.geo_targeting import curated_meta_locations


def test_nested_handles_lift_to_flat_geo_entries():
    campaign_data = {
        "metaMappedLocations": [
            {"name": "Bandra", "lat": 19.05, "lng": 72.83,
             "meta": {"type": "zip", "key": "IN:400050", "name": "400050"}},
            {"name": "India", "scale": "country",
             "meta": {"type": "country", "key": "IN", "name": "India"}},
        ]
    }
    out = curated_meta_locations(campaign_data)
    assert out == [
        {"key": "IN:400050", "name": "400050", "type": "zip"},
        {"key": "IN", "name": "India", "type": "country"},
    ]


def test_keyless_entries_are_skipped():
    # No Meta match → typed but keyless; cannot be targeted by key.
    campaign_data = {"metaMappedLocations": [{"name": "X", "meta": {"type": "city"}}]}
    assert curated_meta_locations(campaign_data) == []


def test_unknown_type_coerced_to_city_not_dropped():
    campaign_data = {"metaMappedLocations": [
        {"name": "SubX", "meta": {"type": "subcity", "key": "777"}},
    ]}
    out = curated_meta_locations(campaign_data)
    assert out == [{"key": "777", "name": "SubX", "type": "city"}]


def test_handle_name_falls_back_to_entry_name():
    campaign_data = {"metaMappedLocations": [
        {"name": "Entry Name", "meta": {"type": "city", "key": "1"}},
    ]}
    assert curated_meta_locations(campaign_data)[0]["name"] == "Entry Name"


def test_legacy_flat_entries_yield_nothing():
    # Pre-nested records (flat meta_key/meta_type) have no nested handle —
    # the caller falls back to the suggested-targets + search path.
    campaign_data = {"metaMappedLocations": [
        {"name": "Old", "meta_key": "9", "meta_type": "city"},
    ]}
    assert curated_meta_locations(campaign_data) == []


def test_empty_and_missing_are_empty():
    assert curated_meta_locations({}) == []
    assert curated_meta_locations({"metaMappedLocations": []}) == []
