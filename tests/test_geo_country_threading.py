"""country_code threading through GeoTargetService: caller wins, IN only as last resort."""
import pytest

from services.geo_target_service import GeoTargetService


@pytest.fixture
def geo_service(monkeypatch):
    monkeypatch.setenv("GOOGLE_ADS_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "test-dev-token")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-maps-key")
    return GeoTargetService(client_code="TEST")


class _FakeResponse:
    status_code = 200
    text = ""

    def json(self):
        return {"geoTargetConstantSuggestions": []}


async def test_resolve_batch_falls_back_to_in(geo_service, monkeypatch):
    captured = {}

    class FakeClient:
        async def post(self, url, headers=None, json=None):
            captured["payload"] = json
            return _FakeResponse()

    monkeypatch.setattr(
        "services.geo_target_service.get_http_client", lambda: FakeClient()
    )
    await geo_service.resolve_locations_batch(["Juhu"])
    assert captured["payload"]["countryCode"] == "IN"


async def test_resolve_batch_uses_caller_country(geo_service, monkeypatch):
    captured = {}

    class FakeClient:
        async def post(self, url, headers=None, json=None):
            captured["payload"] = json
            return _FakeResponse()

    monkeypatch.setattr(
        "services.geo_target_service.get_http_client", lambda: FakeClient()
    )
    await geo_service.resolve_locations_batch(["Marina"], country_code="AE")
    assert captured["payload"]["countryCode"] == "AE"


async def test_grid_geocode_seeds_caller_country(geo_service):
    # No points, no HTTP: seeded country comes straight back
    locations, country = await geo_service._geocode_grid_points_async(
        points=[], country_code="US"
    )
    assert locations == []
    assert country == "US"


async def test_grid_geocode_empty_country_when_underivable(geo_service):
    locations, country = await geo_service._geocode_grid_points_async(points=[])
    assert locations == []
    assert country == ""
