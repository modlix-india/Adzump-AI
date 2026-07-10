"""Bridge mapping tests: adzump session context to ds campaign_data."""
from services.adzump_session_bridge import (
    _resolve_locations,
    map_adzump_context_to_campaign_data,
)


def _context(**overrides):
    base = {
        "product_data": {
            "product_name": "Acme",
            "summary": "sum",
            "place": {
                "address": "12 MG Road, Bengaluru",
                "lat": 12.97,
                "lng": 77.59,
                "country_code": "IN",
            },
            "target_areas": [],
        },
        "campaign_spec": {"platform": "Meta Ads", "location": "Bengaluru"},
    }
    base.update(overrides)
    return base


def test_locations_prefer_place_address():
    assert _resolve_locations(_context()) == ["12 MG Road, Bengaluru"]


def test_locations_fall_back_to_spec_location():
    ctx = _context()
    ctx["product_data"]["place"] = {}
    assert _resolve_locations(ctx) == ["Bengaluru"]


def test_locations_empty_when_no_source():
    assert _resolve_locations({}) == []


def test_country_code_from_place():
    assert map_adzump_context_to_campaign_data(_context())["countryCode"] == "IN"


def test_country_code_tolerates_absent_place():
    ctx = _context()
    ctx["product_data"].pop("place")
    data = map_adzump_context_to_campaign_data(ctx)
    assert data["countryCode"] == ""
    assert data["adzumpLocationLat"] is None
    assert data["adzumpLocationLng"] is None


def test_lat_lng_from_place():
    data = map_adzump_context_to_campaign_data(_context())
    assert data["adzumpLocationLat"] == 12.97
    assert data["adzumpLocationLng"] == 77.59


def test_mapped_locations_split_by_handle_presence():
    ctx = _context()
    ctx["product_data"]["target_areas"] = [
        {"name": "Juhu", "google": {"resourceName": "geoTargetConstants/1"}},
        {"name": "Bandra", "meta": {"type": "city", "key": "777"}},
        {"name": "Both", "google": {"resourceName": "geoTargetConstants/2"},
         "meta": {"type": "zip", "key": "IN:400050"}},
        {"name": "Neither"},
    ]
    data = map_adzump_context_to_campaign_data(ctx)
    assert [a["name"] for a in data["googleMappedLocations"]] == ["Juhu", "Both"]
    assert [a["name"] for a in data["metaMappedLocations"]] == ["Bandra", "Both"]
