import structlog

logger = structlog.get_logger(__name__)


class AssetValidator:
    def validate_suggestions(self, suggestions: list, asset_type: str) -> list:
        max_length = 30 if asset_type == "HEADLINE" else 90

        valid = []
        seen = set()

        for suggestion in suggestions:
            if not isinstance(suggestion, str):
                continue

            # Check length
            if len(suggestion) > max_length:
                logger.warning(
                    "Rejected suggestion (too long)",
                    text=suggestion,
                    length=len(suggestion),
                    max=max_length,
                )
                continue

            # Check duplicates
            normalized = suggestion.lower().strip()
            if normalized in seen:
                continue

            seen.add(normalized)
            valid.append({"text": suggestion, "character_count": len(suggestion)})

        return valid
