"""Tests for curated_meta_locations: nested Meta handles lifted to Location objects."""
import importlib.util
import pathlib

# Load geo_targeting_builder directly to avoid agents/meta/__init__.py pulling in
# heavy agent imports (business_service → scraper_service → playwright).
_spec = importlib.util.spec_from_file_location(
    "geo_targeting_builder",
    pathlib.Path(__file__).parents[2]
    / "agents/meta/payload_builders/adset_builder/targeting_builder/geo_targeting_builder.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
curated_meta_locations = _mod.curated_meta_locations


def test_nested_handles_lift_to_location_objects():
    campaign_data = {
        "metaMappedLocations": [
            {"name": "Bandra", "lat": 19.05, "lng": 72.83,
             "meta": {"type": "zip", "key": "IN:400050", "name": "400050"}},
            {"name": "India", "scale": "country",
             "meta": {"type": "country", "key": "IN", "name": "India"}},
        ]
    }
    out = curated_meta_locations(campaign_data)
    assert len(out) == 2
    assert out[0].key == "IN:400050" and out[0].name == "400050" and out[0].type == "zip"
    assert out[1].key == "IN" and out[1].name == "India" and out[1].type == "country"


def test_keyless_entries_are_skipped():
    campaign_data = {"metaMappedLocations": [{"name": "X", "meta": {"type": "city"}}]}
    assert curated_meta_locations(campaign_data) == []


def test_unknown_type_coerced_to_city_not_dropped():
    campaign_data = {"metaMappedLocations": [
        {"name": "SubX", "meta": {"type": "subcity", "key": "777"}},
    ]}
    out = curated_meta_locations(campaign_data)
    assert len(out) == 1 and out[0].key == "777" and out[0].type == "city"


def test_handle_name_falls_back_to_entry_name():
    campaign_data = {"metaMappedLocations": [
        {"name": "Entry Name", "meta": {"type": "city", "key": "1"}},
    ]}
    assert curated_meta_locations(campaign_data)[0].name == "Entry Name"


def test_legacy_flat_entries_yield_nothing():
    campaign_data = {"metaMappedLocations": [
        {"name": "Old", "meta_key": "9", "meta_type": "city"},
    ]}
    assert curated_meta_locations(campaign_data) == []


def test_empty_and_missing_are_empty():
    assert curated_meta_locations({}) == []
    assert curated_meta_locations({"metaMappedLocations": []}) == []
