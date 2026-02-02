# AdAssetsGenerator – AI-Powered Ad Assets Generation with Retry Logic (V1)

## PURPOSE

`AdAssetsGenerator` is responsible for generating high-quality Google Ads headlines and descriptions using AI, with built-in retry logic to guarantee minimum output requirements.

This service ensures consistent, compliant ad assets by:
1. Generating raw ad copy using OpenAI GPT-4o-mini
2. Applying strict quality filters (length, deduplication, similarity)
3. Progressively relaxing constraints across multiple retry attempts
4. Using a rescue pool fallback to guarantee minimum counts

## HIGH-LEVEL FLOW

### Input:
- `summary`: Business summary data (dict)
- `positive_keywords`: List of keywords to include (list)

### Flow:
1. Initialize retry loop (3 attempts by default)
2. Generate raw headlines/descriptions via LLM
3. Filter by length constraints (20-30 chars for headlines, 75-90 for descriptions)
4. Deduplicate exact matches and similar items
5. Check if minimum requirements met (15 headlines, 4 descriptions)
6. If insufficient → retry with relaxed constraints
7. If all retries fail → activate rescue pool fallback
8. Return final ad assets with audience data

### Output:
```python
{
    "headlines": [str...],        # Min 15 items
    "descriptions": [str...],     # Min 4 items
    "audience": {                 # Targeting suggestions
        "gender": [str...],
        "age_range": [str...]
    }
}
```

## CONFIGURATION & CONSTANTS

### CLASS INITIALIZATION:
```python
AdAssetsGenerator(
    max_attempts=3,           # Number of retry attempts
    min_headlines=15,         # Required headline count
    min_descriptions=4        # Required description count
)
```

### BASE CONFIG (Standard Quality):
```python
{
    "h_min": 20,   # Headline minimum length (chars)
    "h_max": 30,   # Headline maximum length (chars)
    "d_min": 75,   # Description minimum length (chars)
    "d_max": 90    # Description maximum length (chars)
}
```

### PROGRESSIVE RELAXATION (Per Attempt):
| Attempt | Temperature | Similarity (Headlines) | Similarity (Descriptions) |
|---------|-------------|------------------------|---------------------------|
| 1       | 0.7         | 0.8                    | 0.7                       |
| 2       | 0.8         | 0.85                   | 0.75                      |
| 3       | 0.9         | 0.9                    | 0.8                       |

**Formula:**
- `temp = 0.7 + (attempt_num * 0.1)`
- `sim_h = 0.8 + (attempt_num * 0.05)`
- `sim_d = 0.7 + (attempt_num * 0.05)`

### FALLBACK CONFIG (Rescue Pool):
```python
{
    "sim_h": 0.95,   # Very strict similarity (fewer removals)
    "sim_d": 0.85,   # Relaxed similarity for descriptions
    "h_min": 15,     # ⬇️ LOWERED from 20
    "h_max": 30,
    "d_min": 60,     # ⬇️ LOWERED from 75
    "d_max": 90
}
```

### LLM CONFIGURATION:
- **Model**: `gpt-4o-mini`
- **Prompt Template**: `prompts/ad_assets_prompt.txt`
- **Default Generation**: 40 headlines + 15 descriptions per attempt
- **Temperature**: Dynamic per attempt (see table above)

## PRIMARY ENTRY POINT

### Method:
```python
generate(summary, positive_keywords)
```

### Signature:
```python
async def generate(
    self,
    summary: dict,
    positive_keywords: list
) -> dict:
```

### Responsibility:
Orchestrates the entire ad assets generation pipeline with retry logic and guaranteed output.

---

## STEP 1: INITIALIZE RETRY LOOP

### What happens:
```python
all_raw_headlines = []        # Accumulator for ALL attempts
all_raw_descriptions = []     # Accumulator for ALL attempts
last_audience = {}            # Track audience from last attempt

for attempt_num in range(self.max_attempts):  # 0, 1, 2
    config = self._get_attempt_config(attempt_num)
```

### Why:
- Save ALL generated items (even filtered-out ones) for rescue pool
- Track audience data across attempts
- Progressive relaxation via dynamic config

**Methods used:**
- `_get_attempt_config(attempt_num)`

---

## STEP 2: GENERATE RAW AD ASSETS

### Method:
```python
_generate_single_attempt(summary, positive_keywords, config)
```

### What it does:
1. Load prompt template from `ad_assets_prompt.txt`
2. Inject `summary` and `positive_keywords` into prompt
3. Call OpenAI API with current temperature
4. Parse JSON response
5. Extract raw headlines, descriptions, audience data

### LLM Request:
```python
{
    "model": "gpt-4o-mini",
    "temperature": config["temp"],  # 0.7 → 0.8 → 0.9
    "messages": [{"role": "user", "content": prompt}]
}
```

### Returns:
```python
{
    "filtered": {
        "headlines": [filtered items],
        "descriptions": [filtered items],
        "audience": {...}
    },
    "raw_headlines": [ALL generated items],
    "raw_descriptions": [ALL generated items]
}
```

---

## STEP 3: FILTER & DEDUPLICATE

### Method:
```python
_filter_headlines(headlines, config)
_filter_descriptions(descriptions, config)
```

### Filtering Pipeline:
1. **Deduplicate** → Remove duplicates and similar items
2. **Length Filter** → Keep only items within length bounds
3. **Sort by Length** → Descending (longer = more complete)
4. **Slice** → Return top N items (15 headlines, 4 descriptions)

### Deduplication Method:
```python
_deduplicate_items(items, similarity_threshold)
```

**Two-pass approach:**

#### Pass 1: Exact Duplicates (Case-Insensitive)
```python
seen = set()
for item in items:
    if item.lower() not in seen:
        keep item
```

#### Pass 2: Semantic Similarity (SequenceMatcher)
```python
for item in unique_items:
    for existing in final_items:
        ratio = SequenceMatcher(None, item.lower(), existing.lower()).ratio()
        if ratio >= threshold:
            discard item  # Too similar
```

**Example:**
- `"Shop Now"` vs `"shop now"` → Removed (exact duplicate)
- `"Buy Today"` vs `"Buy Now"` → Removed if similarity > 0.8
- `"Premium Quality"` vs `"Shop Now"` → Kept (different)

---

## STEP 4: CHECK REQUIREMENTS

### Success Criteria:
```python
if h_count >= 15 and d_count >= 4:
    return filtered  # ✅ Success! Stop immediately
```

### If Insufficient:
```python
logger.warning("Attempt {N} insufficient - will retry")
# Continue to next attempt with relaxed config
```

**Why progressive relaxation:**
- Attempt 1: High quality, strict filtering
- Attempt 2: Moderate quality, more variety
- Attempt 3: Maximum variety, minimal filtering

---

## STEP 5: ACCUMULATE FOR RESCUE POOL

### What happens:
```python
all_raw_headlines.extend(result["raw_headlines"])
all_raw_descriptions.extend(result["raw_descriptions"])
```

### Why:
Even if an attempt fails, ALL generated items are saved for potential reuse in the rescue pool.

**Example scenario:**
- Attempt 1: 40 headlines generated → 12 pass filters
- Attempt 2: 40 headlines generated → 11 pass filters
- Attempt 3: 40 headlines generated → 13 pass filters
- **Rescue Pool**: 120 total headlines to work with

---

## STEP 6: RESCUE POOL FALLBACK

### Method:
```python
_rescue_pool_fallback(all_headlines, all_descriptions)
```

### Triggered when:
All retry attempts fail to meet minimum requirements.

### Strategy:
1. Combine ALL raw items from ALL attempts
2. Apply **soft minimums** (15-char instead of 20-char for headlines)
3. Use **relaxed similarity** (0.95 instead of 0.8)
4. Sort by length descending (prioritize complete content)
5. Return best available items

### Fallback Config:
```python
{
    "h_min": 15,    # ⬇️ Was 20 (accept shorter headlines)
    "d_min": 60,    # ⬇️ Was 75 (accept shorter descriptions)
    "sim_h": 0.95,  # ⬆️ Was 0.8 (keep more items)
    "sim_d": 0.85   # ⬆️ Was 0.7 (keep more items)
}
```

### Critical Failure Logging:
```python
if h_count < 15 or d_count < 4:
    logger.critical("RESCUE POOL UNABLE TO MEET REQUIREMENTS")
    # Return whatever we have (even if insufficient)
```

---

## COMPLETE FLOW DIAGRAM

```
User Request: generator.generate(summary, keywords)
    ↓
┌───────────────────────────────────────────┐
│ ATTEMPT 1 (temp=0.7, sim=0.8, strict)    │
├───────────────────────────────────────────┤
│ • Generate 40 headlines via LLM          │
│ • Filter: length 20-30 chars             │
│ • Deduplicate: similarity < 0.8          │
│ • Result: 12 headlines ❌ (need 15)      │
│ • Save all 40 to rescue pool             │
└───────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────┐
│ ATTEMPT 2 (temp=0.8, sim=0.85, relaxed)  │
├───────────────────────────────────────────┤
│ • Generate 40 headlines via LLM          │
│ • Filter: length 20-30 chars             │
│ • Deduplicate: similarity < 0.85         │
│ • Result: 14 headlines ❌ (need 15)      │
│ • Save all 40 to rescue pool (80 total)  │
└───────────────────────────────────────────┘
    ↓
┌───────────────────────────────────────────┐
│ ATTEMPT 3 (temp=0.9, sim=0.9, very relax)│
├───────────────────────────────────────────┤
│ • Generate 40 headlines via LLM          │
│ • Filter: length 20-30 chars             │
│ • Deduplicate: similarity < 0.9          │
│ • Result: 16 headlines ✅ SUCCESS!       │
│ • Return immediately                     │
└───────────────────────────────────────────┘
    ↓
✅ Return: {headlines: [16], descriptions: [5], audience: {...}}
```

### If All Attempts Fail:
```
┌───────────────────────────────────────────┐
│ RESCUE POOL FALLBACK                      │
├───────────────────────────────────────────┤
│ • Input: 120 headlines from all attempts │
│ • Filter: length 15-30 chars (softer)    │
│ • Deduplicate: similarity < 0.95 (keep+) │
│ • Sort: by length descending             │
│ • Return: Best 15 available              │
└───────────────────────────────────────────┘
    ↓
🔶 Return: Best effort result (may log critical error)
```

---

## KEY DESIGN DECISIONS

### 1. Progressive Relaxation
**Why:** Prioritize quality on early attempts, gradually increase variety if needed.

### 2. Rescue Pool Strategy
**Why:** Prefer reusing valid but slightly-off-spec items over generating entirely new, potentially lower-quality variations.

### 3. Sort by Length Descending
**Why:** Longer ad copy is generally more complete and informative.

### 4. Two-Pass Deduplication
**Why:** Fast exact matching + semantic similarity catches both obvious and subtle duplicates.

### 5. Fixed Generation Count (40/15)
**Why:** Consistent token usage and simpler retry logic.

---

## METHODS REFERENCE

### Public Methods:
```python
async def generate(summary, positive_keywords) -> dict
```
Main entry point for ad asset generation.

### Private Helper Methods:
```python
def _get_attempt_config(attempt_num: int) -> dict
```
Generate dynamic config with progressive relaxation.

```python
def _deduplicate_items(items: list[str], threshold: float) -> list[str]
```
Two-pass deduplication (exact + semantic similarity).

```python
def _filter_headlines(headlines: list[str], config: dict) -> list[str]
```
Deduplicate, filter by length, sort, and slice to required count.

```python
def _filter_descriptions(descriptions: list[str], config: dict) -> list[str]
```
Same as headlines but with different length constraints.

```python
async def _generate_single_attempt(summary, keywords, config: dict) -> dict
```
Single LLM generation attempt with filtering.

```python
def _rescue_pool_fallback(all_headlines: list[str], all_descriptions: list[str]) -> dict
```
Emergency fallback using all accumulated items with relaxed constraints.

---

## LOGGING & OBSERVABILITY

### Key Log Events:
- `[AdAssets] Starting attempt {N}/{MAX}`
- `[AdAssets] Raw items from LLM` (counts)
- `[AdAssets] Headlines after deduplication` (counts + threshold)
- `[AdAssets] Headlines after length filter` (counts + constraints)
- `[AdAssets] ✓ Success on attempt {N}` (final counts)
- `[AdAssets] Executing rescue pool fallback` (pool sizes)
- `[AdAssets] CRITICAL: Rescue pool unable to meet requirements` ⚠️

### Token Usage Tracking:
```python
logger.info(
    "[AdAssets] Token usage",
    prompt_tokens=...,
    completion_tokens=...,
    total_tokens=...,
    temperature=...
)
```

---

## FINAL OUTPUT

### TargetPlaceResponse Structure:
```python
{
    "headlines": [
        "Premium Quality Products",
        "Shop Latest Collection Now",
        # ... 15 total headlines
    ],
    "descriptions": [
        "Discover our wide range of premium products with fast shipping and great prices.",
        # ... 4 total descriptions
    ],
    "audience": {
        "gender": ["Male", "Female"],
        "age_range": ["25-34", "35-44"]
    }
}
```

### Guarantees:
- ✅ Minimum 15 headlines (or best effort + critical log)
- ✅ Minimum 4 descriptions (or best effort + critical log)
- ✅ All items deduplicated
- ✅ All items within length constraints (or soft minimums in fallback)
- ✅ Audience targeting data included

---

## ERROR HANDLING

### LLM Generation Failure:
Returns empty result, continues to next attempt.

### JSON Parsing Failure:
Uses `safe_json_parse`, returns empty result if unparseable.

### All Attempts Failed (Exceptions):
Raises exception after logging critical error.

### Rescue Pool Insufficient:
Returns best available items + logs critical warning.

---

## USAGE EXAMPLE

```python
from services.ads_service import AdAssetsGenerator

# Initialize generator
generator = AdAssetsGenerator(
    max_attempts=3,
    min_headlines=15,
    min_descriptions=4
)

# Generate ad assets
result = await generator.generate(
    summary={
        "business_type": "E-commerce",
        "description": "Online clothing store..."
    },
    positive_keywords=[
        {"keyword": "fashion", "relevance": 0.95},
        {"keyword": "clothing", "relevance": 0.9}
    ]
)

# Use results
headlines = result["headlines"]        # List[str] - Min 15 items
descriptions = result["descriptions"]  # List[str] - Min 4 items
audience = result["audience"]          # Dict with targeting data
```

### Custom Configuration:
```python
# Stricter requirements for premium campaigns
premium_gen = AdAssetsGenerator(
    max_attempts=5,
    min_headlines=20,
    min_descriptions=6
)

# Relaxed for budget campaigns
budget_gen = AdAssetsGenerator(
    max_attempts=2,
    min_headlines=10,
    min_descriptions=3
)
```
