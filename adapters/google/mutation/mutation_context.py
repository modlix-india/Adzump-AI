from dataclasses import dataclass


@dataclass(frozen=True)
class MutationContext:
    """Contextual information required by operation builders during mutation."""

    account_id: str
    parent_account_id: str
    campaign_id: str
    client_code: str
