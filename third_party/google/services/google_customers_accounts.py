import httpx
import asyncio
import os
from typing import Dict ,List ,Any
from oserver.services import connection

GOOGLE_ADS_API = "https://googleads.googleapis.com/v20"


def _get_auth_headers(client_code : str)-> Dict[str, str]:
    """Build Google Ads API auth headers."""
    access_token = connection.fetch_google_api_token_simple(client_code)
    
    developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")

    if not access_token or not developer_token:
        raise ValueError("Missing GOOGLE_ADS_ACCESS_TOKEN or GOOGLE_ADS_DEVELOPER_TOKEN")

    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "developer-token": developer_token,
    }




async def _fetch_accessible_customers(client: httpx.AsyncClient) -> List[str]:
    """Step 1: Fetch the list of accessible (login) customers."""
    url = f"{GOOGLE_ADS_API}/customers:listAccessibleCustomers"
    response = await client.get(url)
    response.raise_for_status()
    return response.json().get("resourceNames", [])


async def fetch_managed_accounts(client: httpx.AsyncClient, login_customer_id: str, headers: dict)-> List[Dict[str, Any]]:
    """Step 2: For a login customer, return all manager accounts under it."""
    query = """
        SELECT
            customer.id,
            customer.descriptive_name,
            customer.manager
        FROM customer
        WHERE customer.manager = TRUE
    """

    url = f"{GOOGLE_ADS_API}/customers/{login_customer_id}/googleAds:search"
    response = await client.post(url, headers=headers, json={"query": query})
    response.raise_for_status()
    data = response.json()

    accounts = []
    for row in data.get("results", []):
        cust = row.get("customer", {})
        accounts.append({
            "id": cust.get("id"),
            "name": cust.get("descriptiveName"),
            "is_manager": cust.get("manager", False)
        })
    
    return accounts


async def list_manager_customers(client_code: str):
    """
    Fetch all accessible accounts for the authenticated user,
    and fetch their managed accounts concurrently.
    """
    headers = _get_auth_headers(client_code)

    async with httpx.AsyncClient(timeout=40.0, headers=headers) as client:
        # Step 1: Fetch login customers
        resource_names = await _fetch_accessible_customers(client)

        if not resource_names:
            return []

        login_customer_ids = [resource_name.split("/")[-1] for resource_name in resource_names]
        
        # Step 2: Concurrently fetch all managed accounts
        tasks = [
            fetch_managed_accounts(client, cid, headers)
            for cid in login_customer_ids
        ]

        results = await asyncio.gather(*tasks, return_exceptions=False)

        return results
#Helper function to flatten mcc accounts
def flatten_mcc_response(raw_response: Any) -> List[Dict[str, Any]]:
    """
     MCC response is nested (list of single-item lists).
    Input example:
      [[{'id':'1002572931','name':'Test','is_manager':True}], [{'id':'2664052337','name':'Testone','is_manager':True}], ...]
    Output:
      [{'id':'1002572931','name':'Test'}, {'id':'1002572931','name':'Testone'}...]
    """
    flattened_accounts: List[Dict[str, Any]] = []

    if isinstance(raw_response, list):
        for outer_list in raw_response:
            if isinstance(outer_list, list) and outer_list:
                account_data = outer_list[0]  # take the single dict inside

                flattened_accounts.append({
                    "id": str(account_data.get("id", "")).strip(),
                    "name": str(account_data.get("name", "")).strip(),
                })

    # Ensure all entries have an ID
    return [account for account in flattened_accounts if account.get("id")]


async def fetch_customer_accounts(mcc_id: str, client_code:str) -> List[Dict[str, str]]:
    """Fetch L1 customers under a given MCC."""
    headers = _get_auth_headers(client_code)
    url = f"{GOOGLE_ADS_API}/customers/{mcc_id}/googleAds:search"

    query = {
        "query": """
            SELECT
              customer_client.client_customer,
              customer_client.level,
              customer_client.manager,
              customer_client.descriptive_name,
              customer_client.status
            FROM customer_client
            WHERE customer_client.level = 1
        """
    }

    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        response = await client.post(url, json=query)

        if response.status_code == 401:
            raise Exception(f"Unauthorized for MCC {mcc_id}. Invalid access/developer token.")

        response.raise_for_status()
        data = response.json()

        accounts = []

        for item in data.get("results", []):
            c = item.get("customerClient", {})
            if not c.get("manager", False):  # Only non-manager accounts
                accounts.append({
                    "id": c.get("clientCustomer", "").replace("customers/", ""),
                    "name": c.get("descriptiveName", "Unknown"),
                })
        
        return accounts


