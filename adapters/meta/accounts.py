import structlog
from typing import Any

from adapters.meta.client import meta_client

logger = structlog.get_logger(__name__)


class MetaAccountsAdapter:
    async def list_business_accounts(self, client_code: str) -> list[dict[str, Any]]:
        result = await meta_client.get(
            "/me/businesses",
            client_code=client_code,
            params={"fields": "id,name"},
        )
        return [
            {"id": b["id"], "name": b.get("name", b["id"])}
            for b in result.get("data", [])
        ]

    async def list_fb_pages(
        self, business_id: str, client_code: str
    ) -> list[dict[str, Any]]:
        # Try client_pages first (for assets shared with the business)
        result = await meta_client.get(
            f"/{business_id}/client_pages",
            client_code=client_code,
            params={"fields": "id,name"},
        )
        pages = result.get("data", [])

        # If no client pages, try owned_pages
        if not pages:
            result = await meta_client.get(
                f"/{business_id}/owned_pages",
                client_code=client_code,
                params={"fields": "id,name"},
            )
            pages = result.get("data", [])

        return [{"id": p["id"], "name": p.get("name", p["id"])} for p in pages]

    async def list_ig_accounts(
        self, page_id: str, client_code: str, business_id: str | None = None
    ) -> list[dict[str, Any]]:
        # 1. Fetch all pages the user can manage to get the Page Access Token
        # Use /me/accounts which specifically returns page access tokens
        pages_data = await meta_client.get(
            "/me/accounts",
            client_code=client_code,
            params={"fields": "id,access_token", "limit": 100},
        )

        page_token = None
        for page in pages_data.get("data", []):
            if str(page.get("id")) == str(page_id):
                page_token = page.get("access_token")
                break

        if not page_token:
            # Fallback: Try fetching specifically for this page ID
            # (Requires manage_pages or equivalent permission)
            try:
                page_info = await meta_client.get(
                    f"/{page_id}",
                    client_code=client_code,
                    params={"fields": "access_token"},
                )
                page_token = page_info.get("access_token")
            except Exception:
                pass

        if not page_token:
            logger.error("Could not find Page Access Token", page_id=page_id)
            raise ValueError(
                f"Could not find Page Access Token for Page ID {page_id}. Ensure your token has manage_pages permissions."
            )

        logger.info(
            "Acquired Page Access Token", page_id=page_id, token_found=bool(page_token)
        )

        # 2. Use Page Access Token to fetch IG accounts
        # Switching to the specific connection endpoint as suggested by the user
        logger.info(
            "Attempting to fetch IG accounts via connection edge", page_id=page_id
        )

        # Try /{page_id}/instagram_accounts connection
        connection_res = await meta_client.get(
            f"/{page_id}/instagram_accounts",
            client_code=client_code,
            params={"fields": "id,username"},
            access_token=page_token,
        )
        ig_accounts = connection_res.get("data", [])
        logger.info("Connection edge result", count=len(ig_accounts))

        # Also try instagram_business_account field specifically if connection was empty
        if not ig_accounts:
            logger.info(
                "Connection edge empty, trying instagram_business_account field",
                page_id=page_id,
            )
            field_res = await meta_client.get(
                f"/{page_id}",
                client_code=client_code,
                params={"fields": "instagram_business_account{id,username}"},
                access_token=page_token,
            )
            biz_acc = field_res.get("instagram_business_account")
            if biz_acc:
                ig_accounts = [biz_acc]
                logger.info("Found business account via field", ig_id=biz_acc.get("id"))

        # 3. If still empty and we have a business_id, try fetching at the business level
        if not ig_accounts and business_id:
            logger.info(
                "No IG accounts on page connections, trying business level",
                business_id=business_id,
            )
            biz_result = await meta_client.get(
                f"/{business_id}/instagram_accounts",
                client_code=client_code,
                params={"fields": "id,username"},
            )
            ig_accounts = biz_result.get("data", [])
            logger.info("Business level result", count=len(ig_accounts))

        return [
            {"id": str(a["id"]), "name": a.get("username", str(a["id"]))}
            for a in ig_accounts
        ]

    async def list_ad_accounts(
        self, business_id: str, client_code: str
    ) -> list[dict[str, Any]]:
        result = await meta_client.get(
            f"/{business_id}/owned_ad_accounts",
            client_code=client_code,
            params={"fields": "id,name,account_status"},
        )
        logger.info("Fetched ad accounts", count=len(result.get("data", [])), business_id=business_id)
        return [
            {"id": a["id"], "name": a.get("name", a["id"]), "status": a.get("account_status")}
            for a in result.get("data", [])
            if a.get("account_status") == 1
        ]

    async def list_pixels(
        self, ad_account_id: str, client_code: str
    ) -> list[dict[str, Any]]:
        # Ensure ad_account_id starts with act_ if it's just numeric
        if ad_account_id.isdigit():
            ad_account_id = f"act_{ad_account_id}"

        logger.info("Fetching pixels for ad account", ad_account_id=ad_account_id)
        try:
            result = await meta_client.get(
                f"/{ad_account_id}/adspixels",
                client_code=client_code,
                params={"fields": "id,name"},
            )
            pixels = result.get("data", [])
            logger.info("Ad account pixels result", count=len(pixels), ad_account_id=ad_account_id)
            
            return [
                {"id": str(p["id"]), "name": p.get("name", str(p["id"]))}
                for p in pixels
            ]
        except Exception as e:
            logger.error("Error fetching pixels from ad account", error=str(e), ad_account_id=ad_account_id)
            return []

    async def list_business_pixels(
        self, business_id: str, client_code: str
    ) -> list[dict[str, Any]]:
        logger.info("Fetching pixels for business", business_id=business_id)
        try:
            result = await meta_client.get(
                f"/{business_id}/adspixels",
                client_code=client_code,
                params={"fields": "id,name"},
            )
            pixels = result.get("data", [])
            logger.info("Business pixels result", count=len(pixels), business_id=business_id)
            return [
                {"id": str(p["id"]), "name": p.get("name", str(p["id"]))}
                for p in pixels
            ]
        except Exception as e:
            logger.error("Error fetching pixels from business", error=str(e), business_id=business_id)
            return []
