from services.business_service import fetch_products_summary
from services.openai_client import chat_completion
from utils.prompt_loader import load_prompt
from oserver.models.storage_request_model import StorageUpdateRequest
from oserver.services.storage_service import update_storage_page
from fastapi import HTTPException
import re

async def generate_final_summary(
    websiteUrl: str,
    access_token: str,
    client_code: str
):
    try:
        product_data = await fetch_products_summary(
            website_url=websiteUrl,
            access_token=access_token,
            client_code=client_code
        )

        storage_id = product_data.get("storageId")
        if not storage_id:
            raise HTTPException(status_code=400, detail="storageId not found")

        full_storage = product_data.get("storageObject") or {}

        website_summary = product_data.get("summary") or ""
        external_list = product_data.get("externalLinksSummary") or []
        assets_list = product_data.get("assetsSummary") or []

        external_summary = "\n\n".join([
            f"URL: {item.get('url')}\nSummary: {item.get('urlSummary')}"
            for item in external_list if item.get("urlSummary")
        ])

        assets_summary = "\n\n".join([
            f"Asset: {item.get('fileName')}\nSummary: {item.get('fileSummary')}"
            for item in assets_list if item.get("fileSummary")
        ])

        summaries_present = [
            bool(website_summary),
            bool(external_summary),
            bool(assets_summary)
        ]

        if summaries_present.count(True) == 1:
            if website_summary:
                final_summary = website_summary
            elif external_summary:
                final_summary = external_summary
            else:
                final_summary = assets_summary

        else:
            prompt_template = load_prompt("final-summary-prompt.txt")
            prompt = prompt_template.format(
                website_summary=website_summary,
                external_summary=external_summary,
                assets_summary=assets_summary
            )

            response = await chat_completion(
                messages=[
                    {"role": "system", "content": "You are an expert business copywriter."},
                    {"role": "user", "content": prompt},
                ],
                model="gpt-4.1"
            )

            final_summary = response.choices[0].message.content.strip()

        cleaned_final_summary = re.sub(r"\s+", " ", final_summary).strip()

        full_storage["final_summary"] = cleaned_final_summary

        update_request = StorageUpdateRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            clientCode=client_code,
            dataObjectId=storage_id,
            eager=False,
            eagerFields=[],
            dataObject=full_storage
        )

        update_resp = await update_storage_page(
            request=update_request,
            access_token=access_token,
            client_code=client_code
        )

        if not update_resp.success:
            raise HTTPException(status_code=500, detail="Failed to update final summary")

        return {
            "success": True,
            "final_summary": cleaned_final_summary
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
