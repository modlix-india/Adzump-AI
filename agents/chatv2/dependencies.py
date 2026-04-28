"""Dependency providers for ChatV2 agent layer.

TODO: Move account filtering/normalization into the adapters themselves,
      so this layer becomes pure DI without business logic.
"""

from typing import Any

from functools import lru_cache

from adapters.google.accounts import GoogleAccountsAdapter
from adapters.meta.accounts import MetaAccountsAdapter
from adapters.openai.chat import OpenAIChatAdapter


@lru_cache
def get_llm_adapter() -> OpenAIChatAdapter:
    return OpenAIChatAdapter()


@lru_cache
def get_accounts_adapter() -> GoogleAccountsAdapter:
    return GoogleAccountsAdapter()


async def fetch_mcc_accounts(client_code: str) -> list[dict]:
    """Fetch unique MCC (manager) accounts as [{"id": ..., "name": ...}].

    Derives MCCs from the flat account list — each unique login_customer_id
    that manages at least one sub-account is an MCC.
    """
    all_accounts = await get_accounts_adapter().fetch_accessible_accounts(client_code)
    mcc_map: dict[str, dict] = {}
    for acc in all_accounts:
        if not acc.get("is_manager"):
            continue
        lid = str(acc["login_customer_id"])
        if lid not in mcc_map:
            mcc_map[lid] = {
                "id": lid,
                "name": acc.get("login_customer_name") or lid,
            }
    return list(mcc_map.values())


async def fetch_customer_accounts(mcc_id: str, client_code: str) -> list[dict]:
    """Fetch customer accounts under a specific MCC as [{"id": ..., "name": ...}]."""
    all_accounts = await get_accounts_adapter().fetch_accessible_accounts(client_code)
    return [
        {
            "id": str(acc["customer_id"]),
            "name": acc.get("name") or str(acc["customer_id"]),
        }
        for acc in all_accounts
        if str(acc["login_customer_id"]) == mcc_id and str(acc["customer_id"]) != mcc_id
    ]


@lru_cache
def get_meta_accounts_adapter() -> MetaAccountsAdapter:
    return MetaAccountsAdapter()


async def fetch_meta_business_accounts(client_code: str) -> list[dict]:
    """Fetch Meta business accounts, normalized to [{"id": ..., "name": ...}]."""
    raw = await get_meta_accounts_adapter().list_business_accounts(client_code)
    return [{"id": str(a["id"]), "name": a.get("name", a["id"])} for a in raw]


async def fetch_fb_pages(business_id: str, client_code: str) -> list[dict]:
    """Fetch Facebook pages for a business, normalized to [{"id": ..., "name": ...}]."""
    raw = await get_meta_accounts_adapter().list_fb_pages(business_id, client_code)
    return [{"id": str(a["id"]), "name": a.get("name", a["id"])} for a in raw]


async def fetch_ig_accounts(
    page_id: str, client_code: str, business_id: str | None = None
) -> list[dict[str, Any]]:
    """Fetch IG accounts linked to a FB page."""
    raw = await get_meta_accounts_adapter().list_ig_accounts(
        page_id, client_code, business_id
    )
    return [{"id": str(a["id"]), "name": a.get("name", a["id"])} for a in raw]


async def fetch_meta_ad_accounts(business_id: str, client_code: str) -> list[dict]:
    """Fetch Meta ad accounts, normalized to [{"id": ..., "name": ...}]."""
    raw = await get_meta_accounts_adapter().list_ad_accounts(business_id, client_code)
    return [{"id": str(a["id"]), "name": a.get("name", a["id"])} for a in raw]


async def fetch_pixels(ad_account_id: str, client_code: str) -> list[dict]:
    """Fetch Meta pixels for an ad account, normalized to [{"id": ..., "name": ...}]."""
    raw = await get_meta_accounts_adapter().list_pixels(ad_account_id, client_code)
    return [{"id": str(a["id"]), "name": a.get("name", a["id"])} for a in raw]


async def fetch_business_pixels(business_id: str, client_code: str) -> list[dict]:
    """Fetch Meta pixels for a business account."""
    raw = await get_meta_accounts_adapter().list_business_pixels(
        business_id, client_code
    )
    return [{"id": str(a["id"]), "name": a.get("name", a["id"])} for a in raw]
