"""Tests for curated_google_locations: adzump googleMappedLocations to campaign criteria."""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "build_google_search_ad_payload",
    pathlib.Path(__file__).parent.parent
    / "third_party/google/services/build_google_search_ad_payload.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
curated_google_locations = _mod.curated_google_locations


def test_nested_handles_lift_to_resource_name_dicts():
    campaign_data = {
        "googleMappedLocations": [
            {"name": "Bandra", "lat": 19.05, "lng": 72.83,
             "google": {"resourceName": "geoTargetConstants/1007786", "name": "Bandra"}},
            {"name": "Mumbai", "google": {"resourceName": "geoTargetConstants/1007788", "name": "Mumbai"}},
        ]
    }
    out = curated_google_locations(campaign_data)
    assert out == [
        {"resourceName": "geoTargetConstants/1007786"},
        {"resourceName": "geoTargetConstants/1007788"},
    ]


def test_keyless_entries_are_skipped():
    campaign_data = {"googleMappedLocations": [{"name": "X", "google": {}}]}
    assert curated_google_locations(campaign_data) == []


def test_missing_google_handle_skipped():
    campaign_data = {"googleMappedLocations": [{"name": "Old", "google_id": "123"}]}
    assert curated_google_locations(campaign_data) == []


def test_empty_and_missing_are_empty():
    assert curated_google_locations({}) == []
    assert curated_google_locations({"googleMappedLocations": []}) == []
