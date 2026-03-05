from structlog import get_logger
from adapters.google.client import google_ads_client

logger = get_logger(__name__)


class GoogleAccountsAdapter:
    SUB_ACCOUNTS_QUERY = """
    SELECT customer_client.id, customer_client.descriptive_name, customer_client.manager
    FROM customer_client
    WHERE customer_client.status = 'ENABLED'
    """

    def __init__(self) -> None:
        self.client = google_ads_client

    async def fetch_accessible_accounts(self, client_code: str) -> list:
        """Fetch all accessible accounts, expanding manager accounts to sub-accounts."""
        customer_ids = await self._list_customer_ids(client_code)

        all_accounts = []
        seen_ids: set[str] = set()

        for cid in customer_ids:
            is_mgr, acct_name = await self._fetch_account_info(client_code, cid)
            if is_mgr:
                for acc in await self._list_sub_accounts(client_code, cid):
                    if acc["customer_id"] not in seen_ids:
                        seen_ids.add(acc["customer_id"])
                        all_accounts.append(
                            {
                                "customer_id": acc["customer_id"],
                                "name": acc.get("name", ""),
                                "login_customer_id": cid,
                                "login_customer_name": acct_name,
                                "is_manager": True,
                            }
                        )
            else:
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    all_accounts.append(
                        {
                            "customer_id": cid,
                            "name": acct_name,
                            "login_customer_id": cid,
                            "login_customer_name": acct_name,
                            "is_manager": False,
                        }
                    )

        logger.info(
            "Fetched accessible accounts",
            client_code=client_code,
            count=len(all_accounts),
        )
        return all_accounts

    async def _list_customer_ids(self, client_code: str) -> list[str]:
        """List all accessible customer IDs for the authenticated user."""
        data = await self.client.get("customers:listAccessibleCustomers", client_code)
        resource_names = data.get("resourceNames", [])
        customer_ids = [name.split("/")[-1] for name in resource_names]
        logger.info("Found accessible customers", count=len(customer_ids))
        return customer_ids

    async def _fetch_account_info(
        self, client_code: str, customer_id: str
    ) -> tuple[bool, str]:
        """Fetch manager flag and descriptive name for an account."""
        try:
            results = await self.client.search_stream(
                query="SELECT customer.manager, customer.descriptive_name FROM customer",
                customer_id=customer_id,
                login_customer_id=customer_id,
                client_code=client_code,
            )
            customer = results[0].get("customer", {})
            is_manager = customer.get("manager", False)
            name = customer.get("descriptiveName", "")
            return is_manager, name
        except Exception:
            return False, ""

    async def _list_sub_accounts(self, client_code: str, manager_id: str) -> list[dict]:
        """List sub-accounts under a manager (MCC) account."""
        results = await self.client.search_stream(
            query=self.SUB_ACCOUNTS_QUERY,
            customer_id=manager_id,
            login_customer_id=manager_id,
            client_code=client_code,
        )

        accounts = []
        for result in results:
            client_info = result.get("customerClient", {})
            accounts.append(
                {
                    "customer_id": str(client_info.get("id")),
                    "name": client_info.get("descriptiveName"),
                }
            )

        logger.info("Found sub-accounts", manager_id=manager_id, count=len(accounts))
        return accounts
