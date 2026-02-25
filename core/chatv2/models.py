"""
ChatV2 Models - Entities, DTOs, and value objects.
"""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class ChatStatus(str, Enum):
    """Enumeration of possible chat flow statuses."""

    IN_PROGRESS = "in_progress"
    SELECTING_PARENT_ACCOUNT = "selecting_parent_account"
    SELECTING_ACCOUNT = "selecting_account"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"

    @classmethod
    def from_string(cls, value: str) -> "ChatStatus":
        try:
            return cls(value)
        except ValueError:
            return cls.IN_PROGRESS


class AccountType(str, Enum):
    """Type of ad platform account."""

    PARENT_ACCOUNT = "parent_account"
    ACCOUNT = "account"


class AccountOption(BaseModel):
    id: str
    name: str


class AccountSelection(BaseModel):
    """Represents an account selection response for the frontend."""

    type: AccountType
    options: list[AccountOption]

    @classmethod
    def parent_account_selection(cls, options: list[dict]) -> "AccountSelection":
        return cls(
            type=AccountType.PARENT_ACCOUNT,
            options=[AccountOption(**o) for o in options],
        )

    @classmethod
    def account_selection(cls, options: list[dict]) -> "AccountSelection":
        return cls(
            type=AccountType.ACCOUNT, options=[AccountOption(**o) for o in options]
        )


class ChatResponse(BaseModel):
    """Standard chat response DTO."""

    status: str
    reply: str
    collected_data: dict[str, Any]
    progress: str
    account_selection: Optional[dict[str, Any]] = None


class SessionResponse(BaseModel):
    """Session details response DTO."""

    status: str
    data: Optional[dict[str, Any]]
    progress: str
    last_activity: Optional[str] = None
