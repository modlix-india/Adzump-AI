import httpx
from fastapi import HTTPException
from config.meta import META_BASE_URL, META_HTTP_TIMEOUT


async def _search(
    ad_account_id: str,
    access_token: str,
    search_type: str,
    query: str
):
    url = f"{META_BASE_URL}/act_{ad_account_id}/targetingsearch"

    async with httpx.AsyncClient(timeout=META_HTTP_TIMEOUT) as client:
        res = await client.get(
            url,
            params={
                "access_token": access_token,
                "type": search_type,
                "q": query,
                "limit": 5
            }
        )

    if res.status_code != 200:
        raise HTTPException(res.status_code, res.json())

    return res.json().get("data", [])


async def resolve_targeting_items(
    names: list[str],
    ad_account_id: str,
    access_token: str,
    search_type: str
):
    items = []

    for name in names:
        data = await _search(
            ad_account_id=ad_account_id,
            access_token=access_token,
            search_type=search_type,
            query=name
        )

        if data:
            items.append({
                "id": data[0]["id"],
                "name": data[0]["name"]
            })

    return items


def map_gender(gender: str | None):
    if gender == "MALE":
        return [1]
    if gender == "FEMALE":
        return [2]
    return None


def can_use_languages(llm_output: dict) -> bool:
    category = llm_output.get("special_ad_category")
    return category not in ["HOUSING", "CREDIT", "EMPLOYMENT"]


async def build_meta_targeting(
    llm_output: dict,
    ad_account_id: str,
    access_token: str,
    region: str
) -> dict:

    targeting = {
        "geo_locations": {
            "countries": [region]
        },
        "age_min": llm_output["age_range"]["min"],
        "age_max": llm_output["age_range"]["max"],
    }

    genders = map_gender(llm_output.get("gender"))
    if genders:
        targeting["genders"] = genders

    detailed = llm_output.get("detailed_targeting", {})

    interests = await resolve_targeting_items(
        names=detailed.get("interests", []),
        ad_account_id=ad_account_id,
        access_token=access_token,
        search_type="adinterest"
    )

    behaviors = await resolve_targeting_items(
        names=detailed.get("behaviours", []),
        ad_account_id=ad_account_id,
        access_token=access_token,
        search_type="adbehavior"
    )

    demographics = await resolve_targeting_items(
        names=detailed.get("demographics", []),
        ad_account_id=ad_account_id,
        access_token=access_token,
        search_type="adDemographic"
    )

    languages = await resolve_targeting_items(
        names=llm_output.get("languages", []),
        ad_account_id=ad_account_id,
        access_token=access_token,
        search_type="adlanguage"
    )

    flexible_spec = []

    if interests:
        flexible_spec.append({"interests": interests})

    if behaviors:
        flexible_spec.append({"behaviors": behaviors})

    if demographics:
        flexible_spec.append({"demographics": demographics})

    if flexible_spec:
        targeting["flexible_spec"] = flexible_spec

    if languages and can_use_languages(llm_output):
        targeting["languages"] = [{"id": l["id"]} for l in languages]

    return targeting
