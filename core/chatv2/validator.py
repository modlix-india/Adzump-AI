"""Ad Plan Validator - Validates ad plan field values using field registry."""

import asyncio
from typing import Any, Coroutine, Optional

from structlog import get_logger

from core.chatv2.fields import FIELD_REGISTRY, VALIDATORS
from core.chatv2.fields.registry import FieldDef

logger = get_logger(__name__)


async def validate_fields(fields: dict) -> tuple[dict, dict]:
    """
    Validate ad plan fields against registry.

    Returns (valid_fields, errors):
    - valid_fields: {field_name: validated_value}
    - errors: {field_name: {"value": original, "message": error_msg}}
    """
    valid: dict[str, Any] = {}
    errors: dict[str, str] = {}
    async_tasks: list[tuple[str, Any, FieldDef, Coroutine[Any, Any, Any]]] = []

    for name, value in fields.items():
        if value is None:
            continue

        defn = FIELD_REGISTRY.get(name)
        if not defn or not defn.validator:
            valid[name] = value
            continue

        validator = VALIDATORS.get(defn.validator)
        if not validator:
            valid[name] = value
            continue

        if asyncio.iscoroutinefunction(validator):
            async_tasks.append((name, value, defn, validator(value)))
        else:
            result: Any
            error: Optional[str]
            result, error = validator(value)  # type: ignore[misc]
            if error:
                errors[name] = defn.error_msg or error
            else:
                valid[name] = result

    # Run async validators concurrently
    if async_tasks:
        results = await asyncio.gather(
            *[t[3] for t in async_tasks], return_exceptions=True
        )
        for (name, value, defn, _), result in zip(async_tasks, results):
            if isinstance(result, Exception):
                errors[name] = defn.error_msg or str(result)
            else:
                validated, error = result
                if error:
                    errors[name] = defn.error_msg or error
                else:
                    valid[name] = validated

    return valid, errors


def validate_account_selection(selected_id: str, options: list[dict]) -> bool:
    """Check if selected_id is in valid options."""
    return selected_id in {str(opt.get("id")) for opt in options}
