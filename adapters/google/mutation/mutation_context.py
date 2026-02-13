from dataclasses import dataclass
from core.models.optimization import CampaignRecommendation


@dataclass(frozen=True)
class MutationContext:
    """
    Contextual information required by operation builders during mutation.
    """

    campaign: CampaignRecommendation
    client_code: str

    @property
    def parent_account_id(self) -> str:
        return self.campaign.parent_account_id

    @property
    def account_id(self) -> str:
        return self.campaign.account_id

    @property
    def campaign_id(self) -> str:
        return self.campaign.campaign_id
