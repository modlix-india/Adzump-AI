# from datetime import datetime

# def get_unique_suffix():
#     now = datetime.now()
#     return now.strftime("%d/%m/%Y_%H:%M:%S")

# def build_google_ads_payloads(customer_id, ads):
#    # pick values from ads
#     safe_name = ads.get("businessName", ads.business_name or "DefaultBusiness")

#     budget_number = float(ads.get("budget", 0) or 0)

#     amount_micros = int(budget_number * 1_000_000) if budget_number > 0 else None

#     locations = ads.get("locations", [])
#     age_range = ads.get("age_range", [])
#     genders = ads.get("gender", [])
#     keywords = ads.get("keywords", [])

#     ad_details = ads.get("adDetails", {})
#     headlines = ad_details.get("headlines", [])
#     descriptions = ad_details.get("descriptions", [])
#     final_urls = ads.get("finalUrls", [])

#     # ---------- Helpers ----------
#     AGE_BUCKETS = [
#         {"type": "AGE_RANGE_18_24", "min": 18, "max": 24},
#         {"type": "AGE_RANGE_25_34", "min": 25, "max": 34},
#         {"type": "AGE_RANGE_35_44", "min": 35, "max": 44},
#         {"type": "AGE_RANGE_45_54", "min": 45, "max": 54},
#         {"type": "AGE_RANGE_55_64", "min": 55, "max": 64},
#         {"type": "AGE_RANGE_65_UP", "min": 65, "max": 999},
#     ]

#     def pick_age_types(range_list):
#         if len(range_list) != 2:
#             return []
#         min_val, max_val = map(int, range_list)
#         return [
#             b["type"] for b in AGE_BUCKETS
#             if b["min"] <= max_val and b["max"] >= min_val
#         ]

#     def gender_type(g):
#         g = str(g or "").lower()
#         if g == "male": return "MALE"
#         if g == "female": return "FEMALE"
#         return None

#     # ---------- 1) Campaign Budget ----------
#     campaign_budget_payload = {
#         "operations": [
#             {
#                 "create": {
#                     "name": f"{safe_name} Campaign budget {get_unique_suffix()}",
#                     "deliveryMethod": "STANDARD",
#                     **({"amountMicros": amount_micros} if amount_micros else {}),
#                     "explicitlyShared": False,
#                 }
#             }
#         ]
#     }

#     # ---------- 2) Campaign ----------
#     campaign_payload = {
#         "operations": [
#             {
#                 "create": {
#                     "name": f"{safe_name} Campaign {get_unique_suffix()}",
#                     "status": "ENABLED",
#                     "advertisingChannelType": "SEARCH",
#                     "maximizeConversions": {},
#                 }
#             }
#         ]
#     }

#     # ---------- 3) Campaign Criteria (Locations) ----------
#     campaign_criteria_payload = {
#         "operations": [
#             {
#                 "create": {
#                     "location": {"geoTargetConstant": loc["resourceName"]}
#                 }
#             }
#             for loc in locations if isinstance(loc.get("resourceName"), str)
#         ]
#     }

#     # ---------- 4) Ad Group ----------
#     ad_group_payload = {
#         "operations": [
#             {
#                 "create": {
#                     "name": f"{safe_name} Adgroup {get_unique_suffix()}",
#                     "status": "ENABLED",
#                     "type": "SEARCH_STANDARD",
#                 }
#             }
#         ]
#     }

#     # ---------- 5) Ad Group Criteria ----------
#     age_types = pick_age_types(age_range)
#     ad_group_criteria_ops = []

#     # Keywords
#     for k in keywords:
#         if isinstance(k, str) and k.strip():
#             ad_group_criteria_ops.append({
#                 "create": {
#                     "status": "ENABLED",
#                     "keyword": {"text": k.strip(), "matchType": "BROAD"}
#                 }
#             })

#     # Age ranges
#     for age in age_types:
#         ad_group_criteria_ops.append({
#             "create": {"status": "ENABLED", "ageRange": {"type": age}}
#         })

#     # Genders
#     for g in genders:
#         gt = gender_type(g)
#         if gt:
#             ad_group_criteria_ops.append({
#                 "create": {"status": "ENABLED", "gender": {"type": gt}}
#             })

#     ad_group_criteria_payload = {"operations": ad_group_criteria_ops}

#     # ---------- 6) Ad (Responsive Search Ad) ----------
#     ad_obj = {
#         "name": f"{safe_name} Ad {get_unique_suffix()}",
#         "responsiveSearchAd": {}
#     }

#     if headlines:
#         ad_obj["responsiveSearchAd"]["headlines"] = headlines
#     if descriptions:
#         ad_obj["responsiveSearchAd"]["descriptions"] = descriptions
#     if final_urls:
#         ad_obj["finalUrls"] = final_urls

#     if not ad_obj["responsiveSearchAd"]:
#         del ad_obj["responsiveSearchAd"]

#     ad_payload = {
#         "operations": [
#             {"create": {"status": "ENABLED", "ad": ad_obj}}
#         ]
#     }

#     return {
#         "campaignBudgetPayload": campaign_budget_payload,
#         "campaignPayload": campaign_payload,
#         "campaignCriteriaPayload": campaign_criteria_payload,
#         "adGroupPayload": ad_group_payload,
#         "adGroupCriteriaPayload": ad_group_criteria_payload,
#         "adPayload": ad_payload,
#     }



from datetime import datetime

def get_unique_suffix():
    now = datetime.now()
    return now.strftime("%d/%m/%Y_%H:%M:%S")

def build_google_ads_payloads(customer_id, ads):
    safe_name = ads.get("businessName") or ads.get("business_name") or "DefaultBusiness"

    budget_number = float(ads.get("budget", 0) or 0)
    amount_micros = int(budget_number * 1_000_000) if budget_number > 0 else None

    start_date = ads.get("startDate")
    end_date = ads.get("endDate")
    goal = ads.get("goal", "leads")
    final_urls = [ads.get("url")] if ads.get("url") else []

    locations = ads.get("locations", [])
    age_range = ads.get("age_range", [])
    genders = ads.get("gender", [])

    headlines = ads.get("headlines", [])
    descriptions = ads.get("descriptions", [])

    positive_keywords = ads.get("positive_keywords", [])
    negative_keywords = ads.get("negative_keywords", [])

    # ---------- Helpers ----------
    AGE_BUCKETS = [
        {"type": "AGE_RANGE_18_24", "min": 18, "max": 24},
        {"type": "AGE_RANGE_25_34", "min": 25, "max": 34},
        {"type": "AGE_RANGE_35_44", "min": 35, "max": 44},
        {"type": "AGE_RANGE_45_54", "min": 45, "max": 54},
        {"type": "AGE_RANGE_55_64", "min": 55, "max": 64},
        {"type": "AGE_RANGE_65_UP", "min": 65, "max": 999},
    ]

    def pick_age_types(range_list):
        if len(range_list) != 2:
            return []
        min_val, max_val = map(int, range_list)
        return [
            b["type"] for b in AGE_BUCKETS
            if b["min"] <= max_val and b["max"] >= min_val
        ]

    def gender_type(g):
        g = str(g or "").lower()
        if g == "male": return "MALE"
        if g == "female": return "FEMALE"
        return None

    def match_type(mt):
        mt = str(mt or "").upper()
        if mt == "EXACT": return "EXACT"
        if mt == "PHRASE": return "PHRASE"
        return "BROAD"

    # ---------- 1) Campaign Budget ----------
    campaign_budget_payload = {
        "operations": [
            {
                "create": {
                    "name": f"{safe_name} Campaign budget {get_unique_suffix()}",
                    "deliveryMethod": "STANDARD",
                    **({"amountMicros": amount_micros} if amount_micros else {}),
                    "explicitlyShared": False,
                }
            }
        ]
    }

    # ---------- 2) Campaign ----------
    campaign_payload = {
        "operations": [
            {
                "create": {
                    "name": f"{safe_name} Campaign {get_unique_suffix()}",
                    "status": "ENABLED",
                    "advertisingChannelType": "SEARCH",
                    "maximizeConversions": {} if goal == "leads" else {},
                    **({"startDate": start_date} if start_date else {}),
                    **({"endDate": end_date} if end_date else {}),
                }
            }
        ]
    }

    # ---------- 3) Campaign Criteria (Locations) ----------
    campaign_criteria_payload = {
        "operations": [
            {
                "create": {
                    "location": {"geoTargetConstant": loc["resourceName"]}
                }
            }
            for loc in locations if isinstance(loc.get("resourceName"), str)
        ]
    }

    # ---------- 4) Ad Group ----------
    ad_group_payload = {
        "operations": [
            {
                "create": {
                    "name": f"{safe_name} Adgroup {get_unique_suffix()}",
                    "status": "ENABLED",
                    "type": "SEARCH_STANDARD",
                }
            }
        ]
    }

    # ---------- 5) Ad Group Criteria ----------
    age_types = pick_age_types(age_range)
    ad_group_criteria_ops = []

    # Positive Keywords
    for k in positive_keywords:
        kw = k.get("keyword")
        mt = match_type(k.get("match_type"))
        if isinstance(kw, str) and kw.strip():
            ad_group_criteria_ops.append({
                "create": {
                    "status": "ENABLED",
                    "keyword": {"text": kw.strip(), "matchType": mt}
                }
            })

    # Negative Keywords
    for nk in negative_keywords:
        kw = nk.get("keyword")
        if isinstance(kw, str) and kw.strip():
            ad_group_criteria_ops.append({
                "create": {
                    "status": "ENABLED",
                    "negative": True,
                    "keyword": {"text": kw.strip(), "matchType": "BROAD"}
                }
            })

    # Age ranges
    for age in age_types:
        ad_group_criteria_ops.append({
            "create": {"status": "ENABLED", "ageRange": {"type": age}}
        })

    # Genders
    for g in genders:
        gt = gender_type(g)
        if gt:
            ad_group_criteria_ops.append({
                "create": {"status": "ENABLED", "gender": {"type": gt}}
            })

    ad_group_criteria_payload = {"operations": ad_group_criteria_ops}

    # ---------- 6) Ad (Responsive Search Ad) ----------
    ad_obj = {
        "name": f"{safe_name} Ad {get_unique_suffix()}",
        "responsiveSearchAd": {},
    }

    if headlines:
        ad_obj["responsiveSearchAd"]["headlines"] = [{"text": h} for h in headlines]
    if descriptions:
        ad_obj["responsiveSearchAd"]["descriptions"] = [{"text": d} for d in descriptions]
    if final_urls:
        ad_obj["finalUrls"] = final_urls

    if not ad_obj["responsiveSearchAd"]:
        del ad_obj["responsiveSearchAd"]

    ad_payload = {
        "operations": [
            {"create": {"status": "ENABLED", "ad": ad_obj}}
        ]
    }

    return {
        "campaignBudgetPayload": campaign_budget_payload,
        "campaignPayload": campaign_payload,
        "campaignCriteriaPayload": campaign_criteria_payload,
        "adGroupPayload": ad_group_payload,
        "adGroupCriteriaPayload": ad_group_criteria_payload,
        "adPayload": ad_payload,
    }
