from datetime import datetime
from typing import List, Dict, Any

def get_unique_suffix() -> str:
    return datetime.now().strftime("%d/%m/%Y_%H:%M:%S")

def generate_google_ads_mutate_operations(customer_id: str, ads: Dict[str, Any]) -> Dict[str, Any]:
    """
    - Campaign-level assets are created via assetOperation.create (with negative resourceNames)
    - Each created asset is linked to the campaign via campaignAssetOperation.create
    - Ad groups, ad group criteria, and responsive search ads are created
    """
    safe_name = ads.get("businessName") or ads.get("business_name") or "DefaultBusiness"
    budget_number = float(ads.get("budget", 0) or 0)
    amount_micros = int(budget_number * 1_000_000) if budget_number > 0 else None

    
    start_date = datetime.strptime(ads.get("startDate"), "%d/%m/%Y").strftime("%Y-%m-%d")
    end_date = datetime.strptime(ads.get("endDate"), "%d/%m/%Y").strftime("%Y-%m-%d")
    goal = ads.get("goal", "leads")
    geo_target_type_setting = ads.get("geoTargetTypeSetting")
    locations = ads.get("locations", [])
    targetings = ads.get("targeting", [])
    assets = ads.get("assets", {}) or {}

    suffix = get_unique_suffix()
    mutate_ops: List[Dict[str, Any]] = []

    # ---------- Temporary resource names ----------
    budget_resource = "-1"
    campaign_resource = "-2"
    # adgroup resources (-3, -4, ...)
    adgroup_resources = [f"-{i+3}" for i in range(len(targetings))]

    # Asset temp ids start at -100 and increment per asset
    next_asset_id = 100

    # ---------- 1) Campaign Budget ----------
    if amount_micros:
        mutate_ops.append({
            "campaignBudgetOperation": {
                "create": {
                    "resourceName": f"customers/{customer_id}/campaignBudgets/{budget_resource}",
                    "name": f"{safe_name} Campaign budget {suffix}",
                    "amountMicros": amount_micros,
                    "deliveryMethod": "STANDARD",
                    "explicitlyShared": False
                }
            }
        })

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
        **({"geoTargetTypeSetting": geo_target_type_setting} if geo_target_type_setting else {})
    }
    mutate_ops.append({"campaignOperation": {"create": campaign_create}})

    # ---------- 3) Campaign Criteria (locations) ----------
    for loc in locations:
        rn = loc.get("resourceName") if isinstance(loc, dict) else None
        if rn:
            mutate_ops.append({
                "campaignCriterionOperation": {
                    "create": {
                        "campaign": f"customers/{customer_id}/campaigns/{campaign_resource}",
                        "location": {"geoTargetConstant": rn}
                    }
                }
            })

    # ---------- 4) Campaign-level assets creation + linking ----------
    # We'll keep a small helper to add an assetOperation.create and a campaignAssetOperation.create
    def add_asset_and_link(field_type: str, asset_create_body: Dict[str, Any]):
        nonlocal next_asset_id, mutate_ops
        asset_resource = f"-{next_asset_id}"
        next_asset_id += 1

        # Asset creation
        mutate_ops.append({
            "assetOperation": {
                "create": {
                    "resourceName": f"customers/{customer_id}/assets/{asset_resource}",
                    **asset_create_body
                }
            }
        })

        # Link asset to campaign
        mutate_ops.append({
            "campaignAssetOperation": {
                "create": {
                    "asset": f"customers/{customer_id}/assets/{asset_resource}",
                    "campaign": f"customers/{customer_id}/campaigns/{campaign_resource}",
                    "fieldType": field_type
                }
            }
        })

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
                "description1": sl.get("description1") or sl.get("description_1") or sl.get("desc1"),
                "description2": sl.get("description2") or sl.get("description_2") or sl.get("desc2"),
            },
            "finalUrls": urls  # ✅ Correct placement for v20
        }
        add_asset_and_link("SITELINK", asset_body)


    # 4.b Callouts
    for co in assets.get("callouts", []):
        # co may be a string or an object
        callout_text = co if isinstance(co, str) else (co.get("calloutText") or co.get("callout_text"))
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
    "shows":"Shows",
    "insurance coverage":"Insurance coverage",
    "degree programs":"Degree programs",
    "featured hotels":"Featured Hotels",
    "models":"Models"
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
            "structuredSnippetAsset": {
                "header": header_enum,
                "values": values
            }
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


    # ---------- 5) Ad Groups + Criteria + Ads ----------
    AGE_BUCKETS = [
        {"type": "AGE_RANGE_18_24", "min": 18, "max": 24},
        {"type": "AGE_RANGE_25_34", "min": 25, "max": 34},
        {"type": "AGE_RANGE_35_44", "min": 35, "max": 44},
        {"type": "AGE_RANGE_45_54", "min": 45, "max": 54},
        {"type": "AGE_RANGE_55_64", "min": 55, "max": 64},
        {"type": "AGE_RANGE_65_UP", "min": 65, "max": 99},
    ]

    def pick_age_types(range_list: List[int]) -> List[str]:
        if not range_list or len(range_list) != 2:
            return []
        min_val, max_val = map(int, range_list)
        return [b["type"] for b in AGE_BUCKETS if b["min"] <= max_val and b["max"] >= min_val]

    def gender_type(g: str):
        g = str(g or "").lower()
        if g == "male": return "MALE"
        if g == "female": return "FEMALE"
        if g == "undetermined": return "UNDETERMINED"
        return None

    def match_type(mt: str):
        mt = str(mt or "").upper()
        if mt in ["EXACT", "PHRASE"]: return mt
        return "BROAD"

    for i, targeting in enumerate(targetings):
        adgroup_resource = adgroup_resources[i]
        t_type = targeting.get("type", "generic").capitalize()
        adgroup_name = f"{safe_name} {t_type} AdGroup {suffix}"

        # Create AdGroup
        mutate_ops.append({
            "adGroupOperation": {
                "create": {
                    "resourceName": f"customers/{customer_id}/adGroups/{adgroup_resource}",
                    "name": adgroup_name,
                    "campaign": f"customers/{customer_id}/campaigns/{campaign_resource}",
                    "status": "ENABLED",
                    "type": "SEARCH_STANDARD"
                }
            }
        })

        # Positive keywords
        for kw_item in targeting.get("positive_keywords", []):
            kw_text = kw_item.get("keyword")
            if kw_text:
                mutate_ops.append({
                    "adGroupCriterionOperation": {
                        "create": {
                            "adGroup": f"customers/{customer_id}/adGroups/{adgroup_resource}",
                            "status": "ENABLED",
                            "keyword": {
                                "text": kw_text.strip(),
                                "matchType": match_type(kw_item.get("match_type"))
                            }
                        }
                    }
                })

        # Negative keywords
        for nk_item in targeting.get("negative_keywords", []):
            kw_text = nk_item.get("keyword")
            if kw_text:
                mutate_ops.append({
                    "adGroupCriterionOperation": {
                        "create": {
                            "adGroup": f"customers/{customer_id}/adGroups/{adgroup_resource}",
                            "status": "ENABLED",
                            "negative": True,
                            "keyword": {
                                "text": kw_text.strip(),
                                "matchType":"BROAD"
                            }
                        }
                    }
                })

        # Age ranges
        for age_type in pick_age_types(targeting.get("age_range", [])):
            mutate_ops.append({
                "adGroupCriterionOperation": {
                    "create": {
                        "adGroup": f"customers/{customer_id}/adGroups/{adgroup_resource}",
                        "status": "ENABLED",
                        "ageRange": {"type": age_type}
                    }
                }
            })

        # Genders
        for g in targeting.get("genders", []):
            gt = gender_type(g)
            if gt:
                mutate_ops.append({
                    "adGroupCriterionOperation": {
                        "create": {
                            "adGroup": f"customers/{customer_id}/adGroups/{adgroup_resource}",
                            "status": "ENABLED",
                            "gender": {"type": gt}
                        }
                    }
                })

        # Ads (Responsive Search Ad)
        headlines = targeting.get("headlines", [])
        descriptions = targeting.get("descriptions", [])
        final_urls = targeting.get("finalUrls", []) or [ads.get("websiteURL")]

        ad_obj = {"status": "ENABLED", "ad": {}}
        if headlines or descriptions:
            ad_obj["ad"]["responsiveSearchAd"] = {}
            if headlines:
                ad_obj["ad"]["responsiveSearchAd"]["headlines"] = [{"text": h} for h in headlines]
            if descriptions:
                ad_obj["ad"]["responsiveSearchAd"]["descriptions"] = [{"text": d} for d in descriptions]
        if final_urls:
            ad_obj["ad"]["finalUrls"] = final_urls

        mutate_ops.append({
            "adGroupAdOperation": {
                "create": {
                    "adGroup": f"customers/{customer_id}/adGroups/{adgroup_resource}",
                    **ad_obj
                }
            }
        })
    
    # Return final payload
    return {"mutateOperations": mutate_ops}
