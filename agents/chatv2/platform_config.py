"""Platform-specific configuration for account selection flows."""

PLATFORM_CONFIG = {
    "google": {
        "parent_id_field": "loginCustomerId",
        "account_id_field": "customerId",
        "parent_label": "manager account",
        "account_label": "customer account",
        "fetch_parents": "fetch_mcc_accounts",
        "fetch_children": "fetch_customer_accounts",
        "progress_find": "Finding your Google Ads accounts",
        "progress_select_parent": "Selecting Google manager account",
        "progress_load_children": "Loading Google customer accounts",
        "progress_select_account": "Selecting Google customer account",
        "required_fields": [
            "businessName",
            "websiteURL",
            "budget",
            "durationDays",
            "platform",
            "loginCustomerId",
            "customerId",
        ],
    },
    "meta": {
        "parent_id_field": "metaBusinessId",
        "account_id_field": "metaAdAccountId",
        "parent_label": "business account",
        "account_label": "ad account",
        "fetch_parents": "fetch_meta_business_accounts",
        "fetch_children": "fetch_meta_ad_accounts",
        "progress_find": "Finding your Meta business accounts",
        "progress_select_parent": "Selecting Meta business account",
        "progress_load_children": "Loading Meta ad accounts",
        "progress_select_account": "Selecting Meta ad account",
        "required_fields": [
            "businessName",
            "websiteURL",
            "budget",
            "durationDays",
            "platform",
            "metaBusinessId",
            "metaAdAccountId",
        ],
    },
}


def all_fields_collected(ad_plan: dict, config: dict) -> bool:
    """Check if all required fields are present in the ad plan."""
    return all(field in ad_plan for field in config["required_fields"])
