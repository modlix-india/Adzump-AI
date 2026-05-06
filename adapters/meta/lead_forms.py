from typing import Any

from adapters.meta.client import meta_client


class MetaLeadFormAdapter:
    async def create(
        self,
        client_code: str,
        page_id: str,
        payload: dict[str, Any], 
    ) -> dict[str, Any]:

        return await meta_client.post(
            f"/{page_id}/leadgen_forms",
            client_code=client_code,
            json=payload,
        )

    async def get(
        self,
        client_code: str,
        lead_form_id: str,
    ) -> dict[str, Any]:

        return await meta_client.get(
            f"/{lead_form_id}",
            client_code=client_code,
        )   

    async def list(
        self,
        client_code: str,
        page_id: str,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:

        params = {}

        if fields:
            params["fields"] = ",".join(fields)

        return await meta_client.get(
            f"/{page_id}/leadgen_forms",
            client_code=client_code,
            params=params or None,
        )    
