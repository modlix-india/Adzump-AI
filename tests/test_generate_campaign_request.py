"""GenerateCampaignRequest must carry googleMappedLocations to the payload builder."""
from models.search_campaign_data_model import GenerateCampaignRequest


def _request(**overrides):
    base = {
        "customerId": "123",
        "loginCustomerId": "456",
        "businessName": "Acme",
        "budget": 100.0,
        "startDate": "01/07/2026",
        "endDate": "31/07/2026",
        "goal": "leads",
        "websiteURL": "https://acme.example",
        "geoTargetTypeSetting": {},
        "locations": [],
        "targeting": [],
    }
    base.update(overrides)
    return GenerateCampaignRequest(**base)


def test_mapped_locations_survive_model_dump():
    req = _request(googleMappedLocations=[
        {"name": "Juhu", "google": {"resourceName": "geoTargetConstants/1"}},
    ])
    dumped = req.model_dump()
    assert dumped["googleMappedLocations"][0]["google"]["resourceName"] == "geoTargetConstants/1"


def test_mapped_locations_optional():
    assert _request().model_dump()["googleMappedLocations"] is None


def test_locations_no_longer_required():
    base = {k: v for k, v in _request().model_dump().items() if v is not None}
    base.pop("locations")
    assert GenerateCampaignRequest(**base).locations == []
