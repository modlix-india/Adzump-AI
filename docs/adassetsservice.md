# AdAssetsGenerator

Generates Google Ads headlines and descriptions via GPT-4o-mini with retry logic to guarantee minimum output counts.

## Flow

```
generate(summary, keywords)
    │
    ├─ Attempt 1 (temp=0.7, strict similarity)
    ├─ Attempt 2 (temp=0.8, relaxed similarity)
    ├─ Attempt 3 (temp=0.9, very relaxed)
    │      Each attempt: LLM → deduplicate → length filter → check minimums
    │      If minimums met → return immediately
    │
    └─ Rescue Pool Fallback
           Combine ALL raw items from all attempts
           Apply soft minimums (shorter lengths, near-exact dedup only)
           Return best available
```

### Detailed Flow

```
┌───────────────────────────────────────────┐
│ ATTEMPT 1 (temp=0.7, sim=0.8, strict)    │
├───────────────────────────────────────────┤
│ • Generate 40 headlines via LLM          │
│ • Filter: length 20-30 chars             │
│ • Deduplicate: similarity < 0.8          │
│ • Result: 12 headlines (need 15)         │
│ • Save all 40 to rescue pool             │
└───────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────┐
│ ATTEMPT 2 (temp=0.8, sim=0.85, relaxed)  │
├───────────────────────────────────────────┤
│ • Generate 40 headlines via LLM          │
│ • Filter: length 20-30 chars             │
│ • Deduplicate: similarity < 0.85         │
│ • Result: 14 headlines (need 15)         │
│ • Save all 40 to rescue pool (80 total)  │
└───────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────┐
│ ATTEMPT 3 (temp=0.9, sim=0.9, relaxed++) │
├───────────────────────────────────────────┤
│ • Generate 40 headlines via LLM          │
│ • Filter: length 20-30 chars             │
│ • Deduplicate: similarity < 0.9          │
│ • Result: 16 headlines — SUCCESS         │
│ • Return immediately                     │
└───────────────────────────────────────────┘

If all attempts fail:
┌───────────────────────────────────────────┐
│ RESCUE POOL FALLBACK                      │
├───────────────────────────────────────────┤
│ • Input: 120 headlines from all attempts │
│ • Filter: length 15-30 chars (softer)    │
│ • Deduplicate: similarity < 0.95 (keep+) │
│ • Sort: by length descending             │
│ • Return: Best 15 available              │
└───────────────────────────────────────────┘
```

## Output

```python
{
    "headlines": [str...],        # Min 15 items
    "descriptions": [str...],     # Min 4 items
    "audience": {
        "gender": [str...],
        "age_range": [str...]
    }
}
```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_attempts` | 3 | Retry attempts before rescue pool |
| `min_headlines` | 15 | Required headline count |
| `min_descriptions` | 4 | Required description count |

### Progressive Relaxation Per Attempt

| Attempt | Temperature | Similarity (H) | Similarity (D) |
|---------|-------------|-----------------|-----------------|
| 1 | 0.7 | 0.8 | 0.7 |
| 2 | 0.8 | 0.85 | 0.75 |
| 3 | 0.9 | 0.9 | 0.8 |

Formula: `temp = 0.7 + (attempt * 0.1)`, `sim_h = 0.8 + (attempt * 0.05)`, `sim_d = 0.7 + (attempt * 0.05)`

### Length Constraints

| | Headlines | Descriptions |
|---|-----------|-------------|
| Standard | 20-30 chars | 75-90 chars |
| Rescue fallback | 15-30 chars | 60-90 chars |

### LLM Configuration

- **Model**: `gpt-4o-mini`
- **Prompt Template**: `prompts/ad_assets_prompt.txt`
- **Default Generation**: 40 headlines + 15 descriptions per attempt

## Filtering Pipeline

1. **Exact dedup** — case-insensitive
2. **Similarity dedup** — `SequenceMatcher` ratio >= threshold removes item
3. **Length filter** — within min/max bounds
4. **Sort by length desc** — longer = more complete
5. **Slice** — take top N

### Deduplication Examples

- `"Shop Now"` vs `"shop now"` → Removed (exact duplicate)
- `"Buy Today"` vs `"Buy Now"` → Removed if similarity > 0.8
- `"Premium Quality"` vs `"Shop Now"` → Kept (different enough)

## Design Decisions

- **Progressive relaxation**: Prioritize quality first, increase variety only if needed
- **Rescue pool**: Reuse all raw items from failed attempts rather than generating more
- **Sort by length descending**: Longer ad copy is generally more complete and informative
- **Two-pass dedup**: Fast exact match + SequenceMatcher catches both obvious and subtle duplicates
- **Fixed generation count** (40/15 per attempt): Consistent token usage and simpler retry logic

## Error Handling

- **JSON parse failure**: Returns empty result, continues to next attempt
- **LLM exception**: Bubbles up to `generate()` loop; retries until last attempt, then raises
- **Rescue pool insufficient**: Returns best effort + logs `CRITICAL`

## Usage

```python
from services.ads_service import AdAssetsGenerator

generator = AdAssetsGenerator(max_attempts=3, min_headlines=15, min_descriptions=4)

result = await generator.generate(
    summary={"business_type": "E-commerce", "description": "Online clothing store..."},
    positive_keywords=[{"keyword": "fashion", "relevance": 0.95}]
)

headlines = result["headlines"]        # List[str] - Min 15 items
descriptions = result["descriptions"]  # List[str] - Min 4 items
audience = result["audience"]          # Dict with targeting data
```
