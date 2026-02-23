from datetime import datetime
from typing import List, Dict, Any


def get_unique_suffix() -> str:
    return datetime.now().strftime("%d/%m/%Y_%H:%M:%S")


def generate_google_ads_mutate_operations(
    customer_id: str, campaign_data_payload: Dict[str, Any]
) -> Dict[str, Any]:
    """
    - Campaign-level assets are created via assetOperation.create (with negative resourceNames)
    - Each created asset is linked to the campaign via campaignAssetOperation.create
    - Ad groups, ad group criteria, and responsive search ads are created
    """
    campaign_data_payload = campaign_data_payload.model_dump()

    safe_name = (
        campaign_data_payload.get("businessName")
        or campaign_data_payload.get("business_name")
        or "DefaultBusiness"
    )
    budget_number = float(campaign_data_payload.get("budget", 0) or 0)
    amount_micros = int(budget_number * 1_000_000) if budget_number > 0 else None

    start_date = datetime.strptime(
        campaign_data_payload.get("startDate"), "%d/%m/%Y"
    ).strftime("%Y-%m-%d")
    end_date = datetime.strptime(
        campaign_data_payload.get("endDate"), "%d/%m/%Y"
    ).strftime("%Y-%m-%d")
    goal = campaign_data_payload.get("goal", "leads")
    geo_target_type_setting = campaign_data_payload.get("geoTargetTypeSetting")
    locations = campaign_data_payload.get("locations", [])
    targetings = campaign_data_payload.get("targeting", [])
    assets = campaign_data_payload.get("assets", {}) or {}
    network_settings = campaign_data_payload.get("networkSettings")

    suffix = get_unique_suffix()
    mutate_ops: List[Dict[str, Any]] = []

    # ---------- Temporary resource names ----------
    budget_resource = "-1"
    campaign_resource = "-2"
    # adgroup resources (-3, -4, ...)
    adgroup_resources = [f"-{i + 3}" for i in range(len(targetings))]

    # Asset temp ids start at -100 and increment per asset
    next_asset_id = 100

    # ---------- 1) Campaign Budget ----------
    if amount_micros:
        mutate_ops.append(
            {
                "campaignBudgetOperation": {
                    "create": {
                        "resourceName": f"customers/{customer_id}/campaignBudgets/{budget_resource}",
                        "name": f"{safe_name} Campaign budget {suffix}",
                        "amountMicros": amount_micros,
                        "deliveryMethod": "STANDARD",
                        "explicitlyShared": False,
                    }
                }
            }
        )

    # ---------- 2) Campaign ----------
    campaign_create = {
        "resourceName": f"customers/{customer_id}/campaigns/{campaign_resource}",
        "name": f"{safe_name} Campaign {suffix}",
        "campaignBudget": f"customers/{customer_id}/campaignBudgets/{budget_resource}",
        "status": "ENABLED",
        "advertisingChannelType": "SEARCH",
        "containsEuPoliticalAdvertising": "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING",
        "maximizeConversions": {} if goal == "leads" else {},
        **({"startDate": start_date} if start_date else {}),
        **({"endDate": end_date} if end_date else {}),
        **(
            {"geoTargetTypeSetting": geo_target_type_setting}
            if geo_target_type_setting
            else {}
        ),
        "networkSettings": (
            network_settings
            if network_settings
            else {
                "targetGoogleSearch": True,  # Show ads ONLY on the main Google Search engine (google.com)
                "targetSearchNetwork": False,  # Show ads on Google Search Network partners
                "targetPartnerSearchNetwork": False,  # Show ads ONLY on partner search sites (not on Google.com itself)
                "targetContentNetwork": False,  # Show text ads on the Google Display Network (GDN)
            }
        ),
    }
    mutate_ops.append({"campaignOperation": {"create": campaign_create}})

    # ---------- 3) Campaign Criteria (locations) ----------
    for loc in locations:
        rn = loc.get("resourceName") if isinstance(loc, dict) else None
        if rn:
            mutate_ops.append(
                {
                    "campaignCriterionOperation": {
                        "create": {
                            "campaign": f"customers/{customer_id}/campaigns/{campaign_resource}",
                            "location": {"geoTargetConstant": rn},
                        }
                    }
                }
            )

    # ---------- 4) Campaign-level assets creation + linking ----------
    # We'll keep a small helper to add an assetOperation.create and a campaignAssetOperation.create
    def add_asset_and_link(field_type: str, asset_create_body: Dict[str, Any]):
        nonlocal next_asset_id, mutate_ops
        asset_resource = f"-{next_asset_id}"
        next_asset_id += 1

        # Asset creation
        mutate_ops.append(
            {
                "assetOperation": {
                    "create": {
                        "resourceName": f"customers/{customer_id}/assets/{asset_resource}",
                        **asset_create_body,
                    }
                }
            }
        )

        # Link asset to campaign
        mutate_ops.append(
            {
                "campaignAssetOperation": {
                    "create": {
                        "asset": f"customers/{customer_id}/assets/{asset_resource}",
                        "campaign": f"customers/{customer_id}/campaigns/{campaign_resource}",
                        "fieldType": field_type,
                    }
                }
            }
        )

    # ---------- 4.a Sitelinks (Updated for Google Ads v20) ----------
    for sl in assets.get("sitelinks", []):
        link_text = sl.get("sitelink_text") or sl.get("linkText") or sl.get("link_text")

        # Collect URLs from any supported key
        urls = sl.get("finalUrls") or sl.get("final_urls") or sl.get("final_url") or []
        if isinstance(urls, str):
            urls = [urls]
        elif not isinstance(urls, list):
            urls = []

        asset_body = {
            "sitelinkAsset": {
                "linkText": link_text,
                "description1": sl.get("description1")
                or sl.get("description_1")
                or sl.get("desc1"),
                "description2": sl.get("description2")
                or sl.get("description_2")
                or sl.get("desc2"),
            },
            "finalUrls": urls,  # ✅ Correct placement for v20
        }
        add_asset_and_link("SITELINK", asset_body)

    # 4.b Callouts
    for co in assets.get("callouts", []):
        # co may be a string or an object
        callout_text = (
            co
            if isinstance(co, str)
            else (co.get("calloutText") or co.get("callout_text"))
        )
        if not callout_text:
            continue
        asset_body = {"calloutAsset": {"calloutText": callout_text}}
        add_asset_and_link("CALLOUT", asset_body)

    # 4.c Structured Snippets
    # Allowed enum values for structured snippet headers in v20
    ALLOWED_STRUCTURED_SNIPPET_HEADERS = {
        "accommodation": "ACCOMMODATION",
        "brands": "Brands",
        "courses": "Courses",
        "destinations": "Destinations",
        "features": "FEATURES",
        "insurance_types": "INSURANCE_TYPES",
        "neighborhoods": "Neighborhoods",
        "services": "Services",
        "spas": "SPAS",
        "style": "STYLE",
        "styles": "Styles",
        "types": "Types",
        "videos": "VIDEOS",
        "amenities": "Amenities",
        "shows": "Shows",
        "insurance coverage": "Insurance coverage",
        "degree programs": "Degree programs",
        "featured hotels": "Featured Hotels",
        "models": "Models",
    }

    for ss in assets.get("structuredSnippets", []):
        header_input = ss.get("header") or ss.get("headerText")
        values = ss.get("values") or ss.get("valuesList") or []
        if not header_input or not values:
            continue

        # Map input header to allowed enum
        header_enum = ALLOWED_STRUCTURED_SNIPPET_HEADERS.get(header_input.lower())
        if not header_enum:
            # Skip if header is invalid for v20
            continue

        asset_body = {
            "structuredSnippetAsset": {"header": header_enum, "values": values}
        }
        add_asset_and_link("STRUCTURED_SNIPPET", asset_body)

    # 4.d Call Assets
    for ca in assets.get("callAssets", []):
        phone = ca.get("phoneNumber") or ca.get("phone_number")
        country = ca.get("countryCode") or ca.get("country_code")
        if not phone:
            continue
        asset_body = {"callAsset": {"phoneNumber": phone, "countryCode": country}}
        add_asset_and_link("CALL", asset_body)

        # 4. Image Assets (expects base64 or preexisting resourceName)
    for ia in assets.get("imageAssets", []):
        # ia may contain 'resourceName' to reuse an existing asset or 'data' (base64) and 'mimeType'
        if isinstance(ia, dict) and ia.get("resourceName"):
            # link existing asset
            mutate_ops.append(
                {
                    "campaignAssetOperation": {
                        "create": {
                            "asset": ia["resourceName"],
                            "campaign": f"customers/{customer_id}/campaigns/{campaign_resource}",
                            "fieldType": "AD_IMAGE",
                        }
                    }
                }
            )
        else:
            mime = ia.get("mimeType") if isinstance(ia, dict) else None
            data = ia.get("data") if isinstance(ia, dict) else None
            if not data:
                continue
            asset_body = {"imageAsset": {"mimeType": mime, "data": data}}
            add_asset_and_link("IMAGE", asset_body)

    # 4.e WhatsApp (Business Message) Assets
    for wa in assets.get("whatsAppAssets", []):
        starter_message = wa.get("starter_message")
        phone = wa.get("phone_number")
        country = wa.get("countryCode") or "IN"

        if not starter_message or not phone or not country:
            continue

        asset_body = {
            "businessMessageAsset": {
                "starterMessage": starter_message,
                "messageProvider": "WHATSAPP",
                "callToAction": {
                    "callToActionSelection": wa.get(
                        "call_to_action_selection", "BOOK_NOW"
                    ),
                    "callToActionDescription": wa.get(
                        "call_to_action_description", "Click to book now"
                    ),
                },
                "whatsappInfo": {"countryCode": country, "phoneNumber": phone},
            }
        }

        add_asset_and_link("BUSINESS_MESSAGE", asset_body)

    # ---------- 5) Ad Groups + Criteria + Ads ----------
    ALL_AGE_RANGES = [
        "AGE_RANGE_18_24",
        "AGE_RANGE_25_34",
        "AGE_RANGE_35_44",
        "AGE_RANGE_45_54",
        "AGE_RANGE_55_64",
        "AGE_RANGE_65_UP",
    ]

    def gender_type(g: str):
        g = str(g or "").lower()
        if g == "male":
            return "MALE"
        if g == "female":
            return "FEMALE"
        if g == "undetermined":
            return "UNDETERMINED"
        return None

    def match_type(mt: str):
        mt = str(mt or "").upper()
        if mt in ["EXACT", "PHRASE"]:
            return mt
        return "BROAD"

    for i, targeting in enumerate(targetings):
        adgroup_resource = adgroup_resources[i]
        t_type = targeting.get("type", "generic").capitalize()
        adgroup_name = f"{safe_name} {t_type} AdGroup {suffix}"

        # Create AdGroup
        mutate_ops.append(
            {
                "adGroupOperation": {
                    "create": {
                        "resourceName": f"customers/{customer_id}/adGroups/{adgroup_resource}",
                        "name": adgroup_name,
                        "campaign": f"customers/{customer_id}/campaigns/{campaign_resource}",
                        "status": "ENABLED",
                        "type": "SEARCH_STANDARD",
                    }
                }
            }
        )

        # Positive keywords
        for kw_item in targeting.get("positive_keywords", []):
            kw_text = kw_item.get("keyword")
            if kw_text:
                mutate_ops.append(
                    {
                        "adGroupCriterionOperation": {
                            "create": {
                                "adGroup": f"customers/{customer_id}/adGroups/{adgroup_resource}",
                                "status": "ENABLED",
                                "keyword": {
                                    "text": kw_text.strip(),
                                    "matchType": match_type(kw_item.get("match_type")),
                                },
                            }
                        }
                    }
                )

        # Negative keywords
        for nk_item in targeting.get("negative_keywords", []):
            kw_text = nk_item.get("keyword")
            if kw_text:
                mutate_ops.append(
                    {
                        "adGroupCriterionOperation": {
                            "create": {
                                "adGroup": f"customers/{customer_id}/adGroups/{adgroup_resource}",
                                "status": "ENABLED",
                                "negative": True,
                                "keyword": {
                                    "text": kw_text.strip(),
                                    "matchType": "BROAD",
                                },
                            }
                        }
                    }
                )

        # Age ranges — input may come as human-readable strings ("25-34") OR enum strings ("AGE_RANGE_25_34")
        # Normalise both formats to Google Ads enum values before filtering.
        AGE_RANGE_MAP = {
            "18-24": "AGE_RANGE_18_24",
            "25-34": "AGE_RANGE_25_34",
            "35-44": "AGE_RANGE_35_44",
            "45-54": "AGE_RANGE_45_54",
            "55-64": "AGE_RANGE_55_64",
            "65+": "AGE_RANGE_65_UP",
        }
        raw_age_ranges = targeting.get("age_range", [])
        normalised_age_ranges = [
            AGE_RANGE_MAP.get(r, r)
            for r in raw_age_ranges  # pass-through if already an enum
        ]
        selected_age_types = [r for r in normalised_age_ranges if r in ALL_AGE_RANGES]
        for age_type in selected_age_types:
            mutate_ops.append(
                {
                    "adGroupCriterionOperation": {
                        "create": {
                            "adGroup": f"customers/{customer_id}/adGroups/{adgroup_resource}",
                            "status": "ENABLED",
                            "ageRange": {"type": age_type},
                        }
                    }
                }
            )
        # Explicitly exclude unselected age ranges (only when a selection was made)
        if selected_age_types:
            excluded_age_types = [
                r for r in ALL_AGE_RANGES if r not in selected_age_types
            ]
            for age_type in excluded_age_types:
                mutate_ops.append(
                    {
                        "adGroupCriterionOperation": {
                            "create": {
                                "adGroup": f"customers/{customer_id}/adGroups/{adgroup_resource}",
                                "status": "ENABLED",
                                "negative": True,
                                "ageRange": {"type": age_type},
                            }
                        }
                    }
                )

        # Genders
        # ENABLED for selected genders, NEGATIVE for all others
        ALL_GENDERS = ["MALE", "FEMALE", "UNDETERMINED"]
        selected_genders = [
            gt
            for g in targeting.get("genders", [])
            if (gt := gender_type(g)) is not None
        ]
        for gt in selected_genders:
            mutate_ops.append(
                {
                    "adGroupCriterionOperation": {
                        "create": {
                            "adGroup": f"customers/{customer_id}/adGroups/{adgroup_resource}",
                            "status": "ENABLED",
                            "gender": {"type": gt},
                        }
                    }
                }
            )
        # Explicitly exclude unselected genders (only when a selection was made)
        if selected_genders:
            excluded_genders = [g for g in ALL_GENDERS if g not in selected_genders]
            for gt in excluded_genders:
                mutate_ops.append(
                    {
                        "adGroupCriterionOperation": {
                            "create": {
                                "adGroup": f"customers/{customer_id}/adGroups/{adgroup_resource}",
                                "status": "ENABLED",
                                "negative": True,
                                "gender": {"type": gt},
                            }
                        }
                    }
                )

        # Ads (Responsive Search Ad)
        headlines = targeting.get("headlines", [])
        descriptions = targeting.get("descriptions", [])
        final_urls = targeting.get("finalUrls", []) or [
            campaign_data_payload.get("websiteURL")
        ]

        ad_obj = {"status": "ENABLED", "ad": {}}
        if headlines or descriptions:
            ad_obj["ad"]["responsiveSearchAd"] = {}
            if headlines:
                ad_obj["ad"]["responsiveSearchAd"]["headlines"] = [
                    {"text": h} for h in headlines
                ]
            if descriptions:
                ad_obj["ad"]["responsiveSearchAd"]["descriptions"] = [
                    {"text": d} for d in descriptions
                ]
        if final_urls:
            ad_obj["ad"]["finalUrls"] = final_urls

        mutate_ops.append(
            {
                "adGroupAdOperation": {
                    "create": {
                        "adGroup": f"customers/{customer_id}/adGroups/{adgroup_resource}",
                        **ad_obj,
                    }
                }
            }
        )
    # Return final payload
    return {"mutateOperations": mutate_ops}
