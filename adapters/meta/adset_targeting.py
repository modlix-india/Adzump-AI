"""
TODO: Meta detailed targeting resolution (interests, behaviors, demographics)

This module is intentionally commented out for now.

Reason:
- Detailed targeting is currently out of scope for ad set creation.
- Payload construction and Meta targeting resolution will be handled
  by a separate service in a future iteration.

Future plan:
- This file will be reintroduced as a dedicated meta_payload_construct service.
- It will only be responsible for resolving Meta IDs (interests, behaviors, demographics)
  using Meta targeting search APIs.
- No LLM logic or ad set creation logic will live here.

"""


# import httpx
# from fastapi import HTTPException

# from adapters.meta.client import META_BASE_URL, META_HTTP_TIMEOUT
# from adapters.meta.targeting_sanitizer import sanitize_flexible_spec, map_locales



# async def _search(
#     ad_account_id: str,
#     access_token: str,
#     search_type: str,
#     query: str,
# ):
#     url = f"{META_BASE_URL}/act_{ad_account_id}/targetingsearch"

#     async with httpx.AsyncClient(timeout=META_HTTP_TIMEOUT) as client:
#         res = await client.get(
#             url,
#             params={
#                 "access_token": access_token,
#                 "type": search_type,
#                 "q": query,
#                 "limit": 5,
#             },
#         )

#     if res.status_code != 200:
#         raise HTTPException(res.status_code, res.json())

#     return res.json().get("data", [])


# async def resolve_targeting_items(
#     names: list[str],
#     ad_account_id: str,
#     access_token: str,
#     search_type: str,
# ):
#     items = []

#     for name in names:
#         if not name:
#             continue

#         query = name.strip()
#         if not query:
#             continue

#         data = await _search(
#             ad_account_id=ad_account_id,
#             access_token=access_token,
#             search_type=search_type,
#             query=query,
#         )

#         if data:
#             items.append(
#                 {
#                     "id": data[0]["id"],
#                     "name": data[0]["name"],
#                 }
#             )

#     return items


# def map_gender(gender: str | None):
#     if gender == "MALE":
#         return [1]
#     if gender == "FEMALE":
#         return [2]
#     return None


# def can_use_languages(llm_output: dict) -> bool:
#     category = llm_output.get("special_ad_category")
#     return category not in ["HOUSING", "CREDIT", "EMPLOYMENT"]


# async def build_meta_targeting(
#     llm_output: dict,
#     ad_account_id: str,
#     access_token: str,
#     region: str,
# ) -> dict:
#     age_range = llm_output.get("age_range", {})
#     age_min = max(18, age_range.get("min", 18))
#     age_max = min(65, age_range.get("max", 65))

#     targeting = {
#         "geo_locations": {
#             "countries": [region],
#         },
#         "age_min": age_min,
#         "age_max": age_max,
#         "publisher_platforms": ["facebook", "instagram"],
#     }

#     genders = map_gender(llm_output.get("gender"))
#     if genders:
#         targeting["genders"] = genders

#     detailed = llm_output.get("detailed_targeting", {})

#     interests = await resolve_targeting_items(
#         names=detailed.get("interests", []),
#         ad_account_id=ad_account_id,
#         access_token=access_token,
#         search_type="adinterest",
#     )

#     behaviors = await resolve_targeting_items(
#         names=detailed.get("behaviors", []) or detailed.get("behaviours", []),
#         ad_account_id=ad_account_id,
#         access_token=access_token,
#         search_type="adbehavior",
#     )

#     demographics = await resolve_targeting_items(
#         names=detailed.get("demographics", []),
#         ad_account_id=ad_account_id,
#         access_token=access_token,
#         search_type="adDemographic",
#     )

#     flexible_spec = []

#     if interests:
#         flexible_spec.append({"interests": interests})

#     if behaviors:
#         flexible_spec.append({"behaviors": behaviors})

#     if demographics:
#         flexible_spec.append({"demographics": demographics})

#     sanitized_flexible_spec = sanitize_flexible_spec(flexible_spec)
#     if sanitized_flexible_spec:
#         targeting["flexible_spec"] = sanitized_flexible_spec

#     locales = map_locales(llm_output.get("languages", []))
#     if locales:
#         targeting["locales"] = locales

#     return targeting
