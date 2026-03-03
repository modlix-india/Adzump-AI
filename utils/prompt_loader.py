import os
from utils.text_utils import safe_truncate_to_sentence
from structlog import get_logger  # type: ignore
from typing import Any, Dict

logger = get_logger(__name__)


def load_prompt(prompt_name: str) -> str:
    # Get the root directory (Adzump-AI) regardless of where this file is
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prompt_path = os.path.join(root_dir, "prompts", prompt_name)
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def format_prompt(prompt_file: str, **context: Any) -> str:
    try:
        template = load_prompt(prompt_file)
        format_dict = build_template_variables(template, context)
        formatted_prompt = template.format(**format_dict)
        logger.debug(f"Successfully formatted prompt:{prompt_file}")
        return formatted_prompt
    except FileNotFoundError:
        logger.error(f"Prompt file not found:{prompt_file}")
        raise
    except KeyError as e:
        logger.error(f"Missing required filed in the prompt file {prompt_file}:{e}")
        logger.error(f"Available fields:{list(format_dict.keys())}")
        raise
    except Exception as e:
        logger.error(f"Error formatting prompt file {prompt_file}:{e}")
        raise


def build_template_variables(template: str, context: Dict[str, Any]) -> Dict[str, Any]:
    format_dict: Dict[str, Any] = {}
    for key, value in context.items():
        if value is None:
            continue
        if key == "scraped_data":
            format_dict["scraped_data"] = value
            if "{content_summary}" in template:
                format_dict["content_summary"] = safe_truncate_to_sentence(
                    str(value), 2000
                )
            if "{business_summary}" in template:
                # Only populate if not already provided in context to avoid overwriting
                if "business_summary" not in context:
                    format_dict["business_summary"] = safe_truncate_to_sentence(
                        str(value), 2500
                    )
            continue
        if key == "brand_info" and hasattr(value, "brand_name"):
            format_dict["brand_name"] = value.brand_name
            format_dict["business_type"] = value.business_type
            format_dict["primary_location"] = value.primary_location
            format_dict["service_areas"] = (
                ", ".join(value.service_areas) or "Not provided"
            )

            if "{location_context}" in template:
                location_context = ""
                if value.primary_location != "Unknown":
                    location_context += f"Primary Location: {value.primary_location}\n"
                if value.service_areas:
                    location_context += (
                        f"Service Areas: {', '.join(value.service_areas)}\n"
                    )
                format_dict["location_context"] = location_context
            format_dict["brand_info"] = value  # Keep original object
            continue

        if key == "unique_features" and isinstance(value, list):
            format_dict["unique_features"] = value
            if "{features_context}" in template:
                format_dict["features_context"] = (
                    f"Unique Features: {', '.join(value)}\n" if value else ""
                )
            continue

        if key == "suggestions" and isinstance(value, list) and value:
            if hasattr(value[0], "keyword"):
                keyword_lines = []
                for s in value:
                    roi = (
                        s.roi_score
                        if hasattr(s, "roi_score")
                        else s.volume / (1 + s.competitionIndex)
                    )
                    keyword_lines.append(
                        f"{s.keyword} | Volume:{s.volume} | ROI:{roi:.0f} | Competition: {s.competitionIndex:.2f}"
                    )

                format_dict["keywords_text"] = "\n".join(keyword_lines)
            continue

        if key == "positive_keywords" and isinstance(value, list):
            if value:
                if hasattr(value[0], "keyword"):
                    format_dict["positive_text"] = ", ".join(
                        [kw.keyword for kw in value]
                    )
                elif isinstance(value[0], dict) and "keyword" in value[0]:
                    format_dict["positive_text"] = ", ".join(
                        [kw["keyword"] for kw in value]
                    )
                else:
                    format_dict["positive_text"] = "No positive keywords provided"
            else:
                format_dict["positive_text"] = "No positive keywords provided"
            continue
        # handle url specifically
        if key == "url":
            format_dict["url"] = value or "Not provided"
            continue
        # all other passed as-is
        format_dict[key] = value
    # ensure the url is always set
    if "url" not in format_dict:
        format_dict["url"] = "Not provided"
    return format_dict
