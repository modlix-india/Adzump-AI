"""Schema Builder - Auto-generate tool schemas from field registry."""

from core.chatv2.fields.registry import FIELD_REGISTRY

TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def build_tool_schema(name: str, description: str) -> dict:
    """Auto-generate OpenAI tool schema from registry."""
    properties = {
        "reasoning": {
            "type": "string",
            "description": (
                "Brief reasoning about what you extracted and why. "
                "Example: 'User said Valmark Cityville — saving as business name. "
                "No URL or budget mentioned yet, will ask next.'"
            ),
        },
    }
    for field_name, defn in FIELD_REGISTRY.items():
        properties[field_name] = {
            "type": TYPE_MAP.get(defn.type, "string"),
            "description": defn.description,
        }

    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": ["reasoning"],
        },
    }
