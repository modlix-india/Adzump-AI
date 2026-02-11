from oserver.models.storage_request_model import StorageReadRequest
from oserver.services.storage_service import StorageService
from structlog import get_logger

logger = get_logger(__name__)


class CampaignMappingService:
    def __init__(self) -> None:
        self.storage = StorageService()

    async def get_campaign_product_mapping(self, client_code: str) -> dict[str, str]:
        """
        Returns: {campaign_id: product_id}
        """
        request = StorageReadRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            clientCode=client_code,
            filter=None,
            size=200,
        )

        response = await self.storage.read_page_storage(request)
        if not response.success or not response.result:
            logger.warning("Failed to fetch AISuggestedData", client_code=client_code)
            return {}

        records = self._extract_records(response.result)
        return self._build_mapping(records)

    async def get_campaign_mapping_with_summary(
        self, client_code: str
    ) -> dict[str, dict]:
        """
        Returns: {campaign_id: {"product_id": str, "summary": str}}
        """
        request = StorageReadRequest(
            storageName="AISuggestedData",
            appCode="marketingai",
            clientCode=client_code,
            filter=None,
            size=200,
        )

        response = await self.storage.read_page_storage(request)
        if not response.success or not response.result:
            logger.warning("Failed to fetch AISuggestedData", client_code=client_code)
            return {}

        records = self._extract_records(response.result)
        return self._build_mapping_with_summary(records)

    #TODO: Handle in StorageReadResponse
    def _extract_records(self, result: list) -> list:
        """Extract content records from nested response."""
        return result[0].get("result", {}).get("result", {}).get("content", [])

    def _build_mapping(self, records: list) -> dict[str, str]:
        """Build campaign_id → product_id mapping."""
        mapping = {}
        for record in records:
            product_id = record.get("_id")
            for campaign in record.get("campaigns", []):
                campaign_id = str(campaign.get("campaignId", ""))
                if campaign_id:
                    mapping[campaign_id] = product_id
        return mapping

    def _build_mapping_with_summary(self, records: list) -> dict[str, dict]:
        """Build campaign_id → {product_id, summary} mapping."""
        mapping = {}
        for record in records:
            product_id = record.get("_id")
            summary = record.get("finalSummary", "")
            for campaign in record.get("campaigns", []):
                campaign_id = str(campaign.get("campaignId", ""))
                if campaign_id:
                    mapping[campaign_id] = {"product_id": product_id, "summary": summary}
        return mapping


campaign_mapping_service = CampaignMappingService()