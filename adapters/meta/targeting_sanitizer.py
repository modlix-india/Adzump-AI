"""
TODO: Meta targeting sanitization utilities

This module is intentionally not used in the current flow.

Reason:
- Interests, behaviors, and demographics are not generated currently.
- Language locale mapping will be fetched from Meta API instead of hardcoded.

Future plan:
- Reintroduce this as part of meta_payload_construct service
  when detailed targeting is implemented.
"""


# INVALID_INTEREST_KEYWORDS = [
#     "facebook access",
#     "mobile",
#     "device",
#     "android",
#     "ios",
#     "browser",
#     "wifi",
#     "network",
# ]


# LOCALE_CODE_MAP = {
#     "english (all)": 1001,
#     "english (uk)": 24,
#     "english": 1001,
#     "hindi": 46,
#     "telugu": 49,
#     "tamil": 45,
#     "marathi": 56,
# }


# def is_valid_interest(interest: dict) -> bool:
#     name = interest.get("name", "").lower()
#     for keyword in INVALID_INTEREST_KEYWORDS:
#         if keyword in name:
#             return False
#     return True


# def sanitize_flexible_spec(flexible_spec: list[dict]) -> list[dict]:
#     sanitized = []

#     for block in flexible_spec:
#         if "interests" in block:
#             valid_interests = [
#                 {"id": i["id"]}
#                 for i in block["interests"]
#                 if is_valid_interest(i)
#             ]
#             if valid_interests:
#                 sanitized.append({"interests": valid_interests})

#         if "behaviors" in block:
#             valid_behaviors = [{"id": b["id"]} for b in block["behaviors"]]
#             if valid_behaviors:
#                 sanitized.append({"behaviors": valid_behaviors})

#     return sanitized


# def normalize_language(lang: str) -> str:
#     return (
#         lang.lower()
#         .replace("language", "")
#         .replace("_", " ")
#         .strip()
#     )


# def map_locales(languages: list[str]) -> list[int]:
#     locales = []

#     for lang in languages:
#         key = normalize_language(lang)
#         code = LOCALE_CODE_MAP.get(key)
#         if code:
#             locales.append(code)

#     return list(set(locales))


