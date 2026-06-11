import pytest
from datetime import datetime, timedelta
from core.models.meta import (
    MetaAdCreationRequest,
    CampaignPayload,
    AdSetPayload,
    AdPayload,
    Schedule,
    Targeting,
    Location,
    TargetingEntity,
    SpecialAdCategory,
)
from agents.meta.payload_builders.basic_entity_builders import (
    build_campaign_payload,
    build_ad_payload,
)
from agents.meta.payload_builders.adset_builder.adset_builder import build_adset_payload
from agents.meta.payload_builders.creative_builder import build_creative_payload


# Fixtures
@pytest.fixture
def future_dates():
    start = (datetime.now() + timedelta(days=5)).strftime("%d/%m/%Y")
    end = (datetime.now() + timedelta(days=10)).strftime("%d/%m/%Y")
    return start, end


@pytest.fixture
def sample_payload_data(future_dates):
    start_date, end_date = future_dates
    return {
        "ad_account_id": "508128451820487",
        "existing_ids": {
            "campaign_id": "",
            "adset_id": "",
            "creative_id": "",
            "ad_id": "",
        },
        "campaign": {
            "name": "Life by the Lake",
            "objective": "OUTCOME_LEADS",
            "special_ad_categories": ["HOUSING"],
            "special_ad_category_country": ["IN"],
            "status": "PAUSED",
        },
        "adset": {
            "name": "Life by the Lake",
            "destination_type": "WEBSITE",
            "budget": {"type": "DAILY", "amount": 2000},
            "bidding": {
                "billing_event": "IMPRESSIONS",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            },
            "schedule": {"start_time": start_date, "end_time": end_date},
            "promoted_object": {
                "type": "PIXEL",
                "pixel_id": "123425543534",
                "event": "LEAD",
            },
            "targeting": {
                "locations": [{"key": "IN:560038", "name": "560038", "type": "zip"}],
                "interests": [
                    {"id": "6002925538921", "name": "Acting", "type": "interests"}
                ],
                "behaviors": [],
                "demographics": [],
                "age_min": 18,
                "age_max": 65,
                "genders": ["MALE", "FEMALE"],
            },
            "status": "PAUSED",
        },
        "creative": {
            "name": "Life by the Lake Creative",
            "type": "IMAGE",
            "page_id": "332515906622723",
            "primary_texts": ["Experience lakeside living."],
            "headlines": ["Luxury Villas"],
            "image_hashes": ["b5a136d20f5c4e4d993ada2062936e2f"],
            "destination_type": "WEBSITE",
            "call_to_action": {"type": "LEARN_MORE", "url": "https://lifebythelake.in"},
        },
        "ad": {"name": "Life by the Lake", "status": "PAUSED"},
    }


# Validation Tests


def test_create_meta_ad_request_validation(sample_payload_data):
    """Verifies that the root request model validates the production payload format."""
    request = MetaAdCreationRequest.model_validate(sample_payload_data)
    assert request.ad_account_id == "508128451820487"
    assert request.campaign.name == "Life by the Lake"
    assert request.adset.budget.amount == 2000


def test_schedule_date_validation():
    """Verifies that both dd/mm/yyyy and ISO formats are supported."""
    future_iso = (datetime.now() + timedelta(days=1)).date().isoformat()
    future_ui = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")

    # Test UI format
    s1 = Schedule(start_time=future_ui)
    assert s1.start_time.strftime("%d/%m/%Y") == future_ui

    # Test ISO format
    s2 = Schedule(start_time=future_iso)
    assert s2.start_time.isoformat() == future_iso


def test_targeting_validation():
    """Verifies targeting logic for Interest/Behavior/Demographic boundaries."""
    with pytest.raises(ValueError, match="Invalid type 'interests' in behaviors"):
        Targeting(
            locations=[Location(key="IN", name="India", type="country")],
            behaviors=[TargetingEntity(id="1", name="Test", type="interests")],
        )


# Builder Tests


def test_campaign_builder(sample_payload_data):
    """Verifies campaign payload assembly for Meta API."""
    campaign_model = CampaignPayload.model_validate(sample_payload_data["campaign"])
    payload = build_campaign_payload(campaign_model)

    assert payload["name"].startswith("Life by the Lake")
    assert payload["objective"] == "OUTCOME_LEADS"
    # required by Meta v24+ for ABO campaigns (no campaign budget)
    assert payload["is_adset_budget_sharing_enabled"] is False
    # Campaign model conversion to Enum check
    assert SpecialAdCategory.HOUSING in campaign_model.special_ad_categories
    assert "HOUSING" in payload["special_ad_categories"]


def test_adset_builder(sample_payload_data):
    """Verifies adset payload assembly including budget and bidding."""
    adset_model = AdSetPayload.model_validate(sample_payload_data["adset"])
    payload = build_adset_payload(adset_model, is_dynamic_creative=False)

    assert payload["name"].startswith("Life by the Lake")
    assert payload["billing_event"] == "IMPRESSIONS"
    assert "daily_budget" in payload
    assert payload["daily_budget"] == 200000  # 2000 * 100


@pytest.mark.parametrize(
    "loc_type, key",
    [
        ("city", "1017930"),
        ("zip", "IN:560038"),
        ("neighborhood", "2805476"),
        ("country", "IN"),
    ],
)
def test_geo_targeting_builder_types(loc_type, key, sample_payload_data):
    """Verifies that different location types are handled correctly by the targeting builder."""
    adset_data = sample_payload_data["adset"]
    adset_data["targeting"]["locations"] = [
        {"key": key, "name": "Test", "type": loc_type}
    ]

    adset_model = AdSetPayload.model_validate(adset_data)
    payload = build_adset_payload(adset_model, is_dynamic_creative=False)

    targeting = payload.get("targeting", {})
    geo = targeting.get("geo_locations", {})

    # Countries are list of strings in Meta API, others are list of dicts with 'key'
    if loc_type == "country":
        assert key in geo.get("countries", [])
    else:
        type_map = {"city": "cities", "zip": "zips", "neighborhood": "neighborhoods"}
        target_key = type_map[loc_type]
        assert any(loc["key"] == key for loc in geo.get(target_key, []))


def test_creative_builder(sample_payload_data):
    """Verifies creative assembly and dynamic creative detection logic."""
    # Use full request validation to resolve forward references in the union
    request = MetaAdCreationRequest.model_validate(sample_payload_data)
    creative_model = request.creative

    # Single variations -> Not dynamic
    payload = build_creative_payload(creative_model, is_dynamic=False)
    assert "asset_feed_spec" not in payload
    assert "link_data" in payload["object_story_spec"]

    # Multiple variations -> Should be flagged as dynamic by service (tested here via flag)
    payload_dynamic = build_creative_payload(creative_model, is_dynamic=True)
    assert "asset_feed_spec" in payload_dynamic
    # For dynamic, object_story_spec exists but only for page_id
    assert "link_data" not in payload_dynamic["object_story_spec"]


def test_ad_builder(sample_payload_data):
    """Verifies final ad entity assembly."""
    ad_model = AdPayload.model_validate(sample_payload_data["ad"])
    payload = build_ad_payload(ad_model)

    assert payload["name"].startswith("Life by the Lake")
    assert payload["status"] == "PAUSED"
