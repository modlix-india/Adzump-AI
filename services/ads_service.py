import json
from difflib import SequenceMatcher
from services.json_utils import safe_json_parse
from services.openai_client import chat_completion
from utils import prompt_loader
from structlog import get_logger

logger = get_logger(__name__)


def deduplicate_items(items: list[str], similarity_threshold: float = 0.7) -> list[str]:
    if not items:
        return []
    
    # First pass: remove exact duplicates (case-insensitive) while preserving order
    seen_lower = set()
    unique_items = []
    for item in items:
        item_lower = item.lower().strip()
        if item_lower not in seen_lower:
            seen_lower.add(item_lower)
            unique_items.append(item)
    
    # Second pass: remove semantically similar items
    final_items = []
    for item in unique_items:
        is_similar = False
        for existing in final_items:
            ratio = SequenceMatcher(None, item.lower(), existing.lower()).ratio()
            if ratio >= similarity_threshold:
                is_similar = True
                logger.debug(
                    "[AdAssets] Removed similar item",
                    removed=item,
                    similar_to=existing,
                    similarity=round(ratio, 2)
                )
                break
        if not is_similar:
            final_items.append(item)
    
    return final_items


async def generate_ad_assets(summary, positive_keywords):
    try:
        prompt = prompt_loader.format_prompt(
            "ad_assets_prompt.txt", 
            summary_json=json.dumps(summary, indent=2),
            positive_keywords_json=json.dumps(positive_keywords, indent=2)
        )

        response = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4o-mini",
            temperature=0.7
        )
        if response.usage:
            logger.info(
                "[AdAssets] Token usage",
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens
            )

        raw_output = response.choices[0].message.content.strip()
        parsed = safe_json_parse(raw_output)

        if not parsed:
            return parsed

        if "headlines" in parsed:
            original_headlines = parsed["headlines"]
            original_count = len(original_headlines)
            logger.info(
                "[AdAssets] Headlines from model",
                count=original_count,
                headlines=original_headlines
            )
            
            # Deduplicate first, then filter by length
            deduped_headlines = deduplicate_items(original_headlines, similarity_threshold=0.8)
            logger.info(
                "[AdAssets] Headlines after dedup",
                count=len(deduped_headlines),
                headlines=deduped_headlines
            )
            
            filtered_headlines = [
                h for h in deduped_headlines
                if len(h) <= 30
            ]
            filtered_headlines = sorted(filtered_headlines, key=len)
            parsed["headlines"] = filtered_headlines[:15]
            logger.info(
                "[AdAssets] Headlines final",
                count=len(parsed["headlines"]),
                headlines=parsed["headlines"]
            )

        if "descriptions" in parsed:
            original_descriptions = parsed["descriptions"]
            original_desc_count = len(original_descriptions)
            logger.info(
                "[AdAssets] Descriptions from model",
                count=original_desc_count,
                descriptions=original_descriptions
            )
            
            # Deduplicate first, then filter by length
            deduped_descriptions = deduplicate_items(original_descriptions, similarity_threshold=0.7)
            logger.info(
                "[AdAssets] Descriptions after dedup",
                count=len(deduped_descriptions),
                descriptions=deduped_descriptions
            )
            
            filtered_descriptions = [
                d for d in deduped_descriptions
                if len(d) >= 80 and len(d) <= 90
            ]
            filtered_descriptions = sorted(filtered_descriptions, key=len)
            parsed["descriptions"] = filtered_descriptions[:4]
            logger.info(
                "[AdAssets] Descriptions final",
                count=len(parsed["descriptions"]),
                descriptions=parsed["descriptions"]
            )

        return parsed

    except Exception as e:
        return {
            "error": f"Exception occurred: {str(e)}",
            "raw_output": None
        }