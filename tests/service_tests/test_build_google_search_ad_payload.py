from unittest.mock import MagicMock
from third_party.google.services.build_google_search_ad_payload import (
    generate_google_ads_mutate_operations,
)

CUSTOMER_ID = "1234567890"

ALL_AGE_ENUMS = {
    "AGE_RANGE_18_24",
    "AGE_RANGE_25_34",
    "AGE_RANGE_35_44",
    "AGE_RANGE_45_54",
    "AGE_RANGE_55_64",
    "AGE_RANGE_65_UP",
}

ALL_GENDER_ENUMS = {"MALE", "FEMALE", "UNDETERMINED"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(targeting_overrides: dict) -> MagicMock:
    """
    Build a minimal GenerateCampaignRequest mock so model_dump() returns
    a dict the payload builder can consume without touching the DB or network.
    """
    targeting = {
        "positive_keywords": [],
        "negative_keywords": [],
        "headlines": ["Test Headline One", "Test Headline Two", "Test Headline Three"],
        "descriptions": ["Test description one.", "Test description two."],
        "age_range": [],
        "genders": [],
        "type": "generic",
        **targeting_overrides,
    }

    mock = MagicMock()
    mock.customerId = CUSTOMER_ID
    mock.model_dump.return_value = {
        "businessName": "TestBiz",
        "budget": 500,
        "startDate": "01/03/2026",
        "endDate": "31/03/2026",
        "goal": "leads",
        "websiteURL": "https://example.com",
        "customerId": CUSTOMER_ID,
        "loginCustomerId": "9999999999",
        "locations": [],
        "assets": {},
        "geoTargetTypeSetting": None,
        "networkSettings": None,
        "targeting": [targeting],
    }
    return mock


def _extract_age_criteria(ops: list) -> list:
    """Return all adGroupCriterionOperation entries that contain an ageRange."""
    return [
        op["adGroupCriterionOperation"]["create"]
        for op in ops
        if "adGroupCriterionOperation" in op
        and "ageRange" in op["adGroupCriterionOperation"]["create"]
    ]


def _extract_gender_criteria(ops: list) -> list:
    """Return all adGroupCriterionOperation entries that contain a gender."""
    return [
        op["adGroupCriterionOperation"]["create"]
        for op in ops
        if "adGroupCriterionOperation" in op
        and "gender" in op["adGroupCriterionOperation"]["create"]
    ]


# ===========================================================================
# AGE RANGE TESTS
# ===========================================================================


class TestAgeRangeTargeting:
    # --- Input format tests -------------------------------------------------

    def test_human_readable_age_range_accepted(self):
        """Human-readable strings like '25-34' should be normalised and included."""
        req = _make_request({"age_range": ["25-34", "35-44", "45-54"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        age_criteria = _extract_age_criteria(result["mutateOperations"])

        enabled = {c["ageRange"]["type"] for c in age_criteria if not c.get("negative")}
        assert enabled == {"AGE_RANGE_25_34", "AGE_RANGE_35_44", "AGE_RANGE_45_54"}

    def test_enum_age_range_accepted(self):
        """Enum strings like 'AGE_RANGE_25_34' should pass through unchanged."""
        req = _make_request({"age_range": ["AGE_RANGE_25_34", "AGE_RANGE_35_44"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        age_criteria = _extract_age_criteria(result["mutateOperations"])

        enabled = {c["ageRange"]["type"] for c in age_criteria if not c.get("negative")}
        assert enabled == {"AGE_RANGE_25_34", "AGE_RANGE_35_44"}

    def test_mixed_age_range_formats_accepted(self):
        """A mix of human-readable and enum strings should both be accepted."""
        req = _make_request({"age_range": ["25-34", "AGE_RANGE_45_54"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        age_criteria = _extract_age_criteria(result["mutateOperations"])

        enabled = {c["ageRange"]["type"] for c in age_criteria if not c.get("negative")}
        assert enabled == {"AGE_RANGE_25_34", "AGE_RANGE_45_54"}

    def test_age_18_24_human_readable(self):
        req = _make_request({"age_range": ["18-24"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        age_criteria = _extract_age_criteria(result["mutateOperations"])

        enabled = {c["ageRange"]["type"] for c in age_criteria if not c.get("negative")}
        assert "AGE_RANGE_18_24" in enabled

    def test_age_65_plus_human_readable(self):
        req = _make_request({"age_range": ["65+"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        age_criteria = _extract_age_criteria(result["mutateOperations"])

        enabled = {c["ageRange"]["type"] for c in age_criteria if not c.get("negative")}
        assert "AGE_RANGE_65_UP" in enabled

    # --- ENABLED / NEGATIVE logic -------------------------------------------

    def test_unselected_age_ranges_are_negated(self):
        """Age ranges not in the selection should appear as negative criteria."""
        selected = {"AGE_RANGE_25_34", "AGE_RANGE_35_44"}
        req = _make_request({"age_range": list(selected)})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        age_criteria = _extract_age_criteria(result["mutateOperations"])

        negated = {c["ageRange"]["type"] for c in age_criteria if c.get("negative")}
        expected_negated = ALL_AGE_ENUMS - selected
        assert negated == expected_negated

    def test_total_age_criteria_count(self):
        """Selecting N ranges should produce N ENABLED + (6-N) NEGATIVE criteria."""
        selected = ["25-34", "35-44"]  # 2 selections
        req = _make_request({"age_range": selected})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        age_criteria = _extract_age_criteria(result["mutateOperations"])

        assert len(age_criteria) == 6  # always all 6 ranges covered

    def test_all_age_ranges_selected_produces_no_negatives(self):
        """When all 6 ranges are selected, there should be zero negative age criteria."""
        all_ranges = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
        req = _make_request({"age_range": all_ranges})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        age_criteria = _extract_age_criteria(result["mutateOperations"])

        negated = [c for c in age_criteria if c.get("negative")]
        assert len(negated) == 0
        assert len(age_criteria) == 6

    # --- Edge cases ---------------------------------------------------------

    def test_empty_age_range_produces_no_age_criteria(self):
        """Empty age_range → Google targets all ages → no age operations added."""
        req = _make_request({"age_range": []})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        age_criteria = _extract_age_criteria(result["mutateOperations"])

        assert age_criteria == []

    def test_missing_age_range_field_produces_no_age_criteria(self):
        """Omitting age_range entirely should behave the same as an empty list."""
        targeting = {
            "positive_keywords": [],
            "negative_keywords": [],
            "headlines": ["H1", "H2", "H3"],
            "descriptions": ["D1", "D2"],
            "genders": [],
            "type": "generic",
            # no "age_range" key
        }
        mock = MagicMock()
        mock.customerId = CUSTOMER_ID
        mock.model_dump.return_value = {
            "businessName": "TestBiz",
            "budget": 500,
            "startDate": "01/03/2026",
            "endDate": "31/03/2026",
            "goal": "leads",
            "websiteURL": "https://example.com",
            "customerId": CUSTOMER_ID,
            "loginCustomerId": "9999999999",
            "locations": [],
            "assets": {},
            "geoTargetTypeSetting": None,
            "networkSettings": None,
            "targeting": [targeting],
        }
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, mock)
        age_criteria = _extract_age_criteria(result["mutateOperations"])
        assert age_criteria == []

    def test_unknown_age_range_value_is_silently_dropped(self):
        """Garbage values like 'unknown-range' should be ignored, not raise an error."""
        req = _make_request({"age_range": ["unknown-range", "bad-value"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        age_criteria = _extract_age_criteria(result["mutateOperations"])

        # No valid selection → no age criteria at all
        assert age_criteria == []

    def test_partial_unknown_values_do_not_block_valid_ones(self):
        """Valid entries should still be processed even when mixed with invalid ones."""
        req = _make_request({"age_range": ["25-34", "bad-value", "45-54"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        age_criteria = _extract_age_criteria(result["mutateOperations"])

        enabled = {c["ageRange"]["type"] for c in age_criteria if not c.get("negative")}
        assert enabled == {"AGE_RANGE_25_34", "AGE_RANGE_45_54"}


# ===========================================================================
# GENDER TESTS
# ===========================================================================


class TestGenderTargeting:
    # --- Input format tests -------------------------------------------------

    def test_capitalized_gender_accepted(self):
        """'Male' and 'Female' (title-case) should be accepted."""
        req = _make_request({"genders": ["Male", "Female"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        gender_criteria = _extract_gender_criteria(result["mutateOperations"])

        enabled = {
            c["gender"]["type"] for c in gender_criteria if not c.get("negative")
        }
        assert enabled == {"MALE", "FEMALE"}

    def test_uppercase_gender_accepted(self):
        """'MALE' and 'FEMALE' (all caps) should be accepted."""
        req = _make_request({"genders": ["MALE", "FEMALE"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        gender_criteria = _extract_gender_criteria(result["mutateOperations"])

        enabled = {
            c["gender"]["type"] for c in gender_criteria if not c.get("negative")
        }
        assert enabled == {"MALE", "FEMALE"}

    def test_lowercase_gender_accepted(self):
        """'male' and 'female' (lowercase) should be accepted."""
        req = _make_request({"genders": ["male", "female"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        gender_criteria = _extract_gender_criteria(result["mutateOperations"])

        enabled = {
            c["gender"]["type"] for c in gender_criteria if not c.get("negative")
        }
        assert enabled == {"MALE", "FEMALE"}

    def test_undetermined_gender_accepted(self):
        req = _make_request({"genders": ["undetermined"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        gender_criteria = _extract_gender_criteria(result["mutateOperations"])

        enabled = {
            c["gender"]["type"] for c in gender_criteria if not c.get("negative")
        }
        assert "UNDETERMINED" in enabled

    # --- ENABLED / NEGATIVE logic -------------------------------------------

    def test_unselected_genders_are_negated(self):
        """Genders not selected should be added as negative criteria."""
        req = _make_request({"genders": ["Male", "Female"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        gender_criteria = _extract_gender_criteria(result["mutateOperations"])

        negated = {c["gender"]["type"] for c in gender_criteria if c.get("negative")}
        assert negated == {"UNDETERMINED"}

    def test_single_gender_negates_other_two(self):
        """Selecting only 'Male' should negate 'FEMALE' and 'UNDETERMINED'."""
        req = _make_request({"genders": ["Male"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        gender_criteria = _extract_gender_criteria(result["mutateOperations"])

        enabled = {
            c["gender"]["type"] for c in gender_criteria if not c.get("negative")
        }
        negated = {c["gender"]["type"] for c in gender_criteria if c.get("negative")}

        assert enabled == {"MALE"}
        assert negated == {"FEMALE", "UNDETERMINED"}

    def test_all_genders_selected_produces_no_negatives(self):
        """Selecting all 3 genders should result in zero negative gender criteria."""
        req = _make_request({"genders": ["Male", "Female", "Undetermined"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        gender_criteria = _extract_gender_criteria(result["mutateOperations"])

        negated = [c for c in gender_criteria if c.get("negative")]
        assert len(negated) == 0
        assert len(gender_criteria) == 3

    def test_total_gender_criteria_count(self):
        """Selecting N genders produces N ENABLED + (3-N) NEGATIVE criteria → always 3 total."""
        req = _make_request({"genders": ["Male", "Female"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        gender_criteria = _extract_gender_criteria(result["mutateOperations"])

        assert len(gender_criteria) == 3

    # --- Edge cases ---------------------------------------------------------

    def test_empty_genders_produces_no_gender_criteria(self):
        """Empty genders list → Google targets all → no gender operations added."""
        req = _make_request({"genders": []})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        gender_criteria = _extract_gender_criteria(result["mutateOperations"])

        assert gender_criteria == []

    def test_unknown_gender_value_is_silently_dropped(self):
        """Unrecognised gender strings should be ignored, not raise an error."""
        req = _make_request({"genders": ["nonbinary", "unknown"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        gender_criteria = _extract_gender_criteria(result["mutateOperations"])

        assert gender_criteria == []

    def test_partial_unknown_genders_do_not_block_valid_ones(self):
        """Valid genders should be processed even when mixed with invalid ones."""
        req = _make_request({"genders": ["Male", "invalid_value"]})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        gender_criteria = _extract_gender_criteria(result["mutateOperations"])

        enabled = {
            c["gender"]["type"] for c in gender_criteria if not c.get("negative")
        }
        assert enabled == {"MALE"}

    # --- Combined: age + gender together ------------------------------------

    def test_age_and_gender_combined_do_not_interfere(self):
        """Age and gender criteria should be independent — selecting both should not affect each other's counts."""
        req = _make_request(
            {
                "age_range": ["25-34", "35-44"],
                "genders": ["Male", "Female"],
            }
        )
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        ops = result["mutateOperations"]

        age_criteria = _extract_age_criteria(ops)
        gender_criteria = _extract_gender_criteria(ops)

        assert len(age_criteria) == 6  # 2 enabled + 4 negated
        assert len(gender_criteria) == 3  # 2 enabled + 1 negated

    def test_empty_age_and_gender_produces_no_demographic_criteria(self):
        """Both empty → zero demographic criteria."""
        req = _make_request({"age_range": [], "genders": []})
        result = generate_google_ads_mutate_operations(CUSTOMER_ID, req)
        ops = result["mutateOperations"]

        assert _extract_age_criteria(ops) == []
        assert _extract_gender_criteria(ops) == []
