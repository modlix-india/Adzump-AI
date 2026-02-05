# AssetOptimizationService – AI-Powered RSA Asset Optimizer with 5-Tier Fallback (V1)

## PURPOSE

`AssetOptimizationService` identifies and optimizes LOW-performing Google Ads RSA (Responsive Search Ad) assets by generating AI-powered replacement suggestions using semantic analysis and LLM generation.

This service ensures intelligent optimization by:
1. Analyzing asset performance data across campaigns
2. Categorizing assets into performance tiers
3. Finding semantically similar high-performing assets
4. Generating contextual replacements using 5-tier fallback strategy
5. Validating suggestions against Google Ads constraints

## HIGH-LEVEL FLOW

### Input:
- `customer_id`: Google Ads customer ID
- `campaign_id`: Campaign ID to analyze (or omit for bulk analysis)
- `access_token`: Google Ads API access token
- `login_customer_id`: Manager account ID (optional for standalone accounts)

### Flow:
1. Fetch asset performance data from Google Ads API
2. Fetch asset text content
3. Categorize assets into performance tiers (LOW, GOOD/BEST, LEARNING, etc.)
4. For each LOW asset:
   - Find similar high-performing assets (semantic similarity)
   - Generate replacement suggestions via LLM
   - Validate character limits and deduplicate
5. Return structured suggestions (add/remove pairs)

### Output:
```json
{
    "campaign_id": "21367850110",
    "campaign_name": "Greenesto Primus Campaign",
    "total_low_assets": 3,
    "total_suggestions": 12,
    "suggestions": [
        {
            "id": "144066891891",
            "type": "HEADLINE",
            "text": "Old Headline",
            "label": "remove",
            "reason": "LOW performance (0 impressions)",
            "ad_group_id": "123456",
            "ad_id": "789012",
            "campaign_id": "21367850110",
            "based_on": "tier_1"
        },
        {
            "id": null,
            "type": "HEADLINE",
            "text": "Premium Greenesto Products",
            "label": "add",
            "reason": "Replacement for LOW asset",
            "ad_group_id": "123456",
            "ad_id": "789012",
            "campaign_id": "21367850110",
            "replaces_asset_id": "144066891891",
            "based_on": "tier_1"
        }
    ]
}
```

## CONFIGURATION & CONSTANTS

### GOOGLE ADS API:
```python
GOOGLE_ADS_API_VERSION = "v20"
SEARCH_ENDPOINT        = /customers/{customer_id}/googleAds:search
```

### PERFORMANCE LABELS (Google Ads):
- `GOOD` / `BEST`    → High-performing assets (tier_1)
- `LEARNING`         → Assets still gathering data (tier_2)
- `PENDING`          → Newly added assets (tier_2)
- `LOW`              → Underperforming assets (target for optimization)
- `UNSPECIFIED`      → Other assets (tier_3)

### SIMILARITY THRESHOLDS (Cosine Similarity):
```python
MIN_SIMILARITY_THRESHOLD = 0.7  # For finding related assets
TOP_K_SIMILAR           = 5     # Max similar assets to use as examples
```

### LLM CONFIGURATION:
- **Generation Model**: `gpt-4o-mini`
- **Embedding Model**: `text-embedding-3-small`
- **Prompt Template**: `prompts/asset_optimization_prompt.txt`
- **Temperature**: 0.8 (balanced creativity)

### VALIDATION LIMITS:
```python
HEADLINE_MAX_CHARS     = 30
DESCRIPTION_MAX_CHARS  = 90
SUGGESTIONS_GENERATED  = 5   # Generate 5 options from LLM for safety
SUGGESTIONS_PER_ASSET  = 1   # Return only best 1 (1:1 replacement ratio)
```

**Strategy**: Generate multiple (5) to ensure at least 1 passes validation, but only return the best one to maintain 1:1 replacement ratio.

## PRIMARY ENTRY POINTS

### Method 1: Single Campaign Analysis
```python
analyze_campaign(customer_id, campaign_id, access_token, login_customer_id)
```

**Signature:**
```python
async def analyze_campaign(
    customer_id: str,
    campaign_id: str,
    access_token: str,
    login_customer_id: str
) -> dict
```

**Responsibility:**
Analyzes a single campaign and generates optimization suggestions for all LOW assets.

### Method 2: Bulk Analysis (All Campaigns)
```python
analyze_all_campaigns(customer_id, access_token, login_customer_id)
```

**Signature:**
```python
async def analyze_all_campaigns(
    customer_id: str,
    access_token: str,
    login_customer_id: str
) -> dict
```

**Responsibility:**
Fetches all ENABLED SEARCH campaigns and processes them in parallel.

**Output includes:**
- `total_campaigns`: Total campaigns found
- `successful`: Successfully processed count
- `failed`: Failed campaigns count
- `results`: Array of campaign results
- `errors`: Array of error details

## CORE WORKFLOW DETAILS

### STEP 1: FETCH ASSET PERFORMANCE DATA
**Method:**
```python
_fetch_asset_performance(customer_id, campaign_id, access_token, login_customer_id)
```

**What it fetches:**
- Asset IDs
- Performance labels (GOOD, LOW, LEARNING, etc.)
- Metrics (impressions, clicks)
- Asset type (HEADLINE vs DESCRIPTION)
- Campaign/Ad Group/Ad context

**Query fields:**
```sql
SELECT 
    ad_group_ad_asset_view.performance_label,
    ad_group_ad_asset_view.asset,
    ad_group_ad_asset_view.field_type,
    metrics.impressions,
    campaign.name,
    ad_group.name,
    ad_group_ad.ad
FROM ad_group_ad_asset_view
WHERE campaign.id = {campaign_id}
```

### STEP 2: FETCH ASSET TEXT
**Method:**
```python
_fetch_asset_text(asset_ids, customer_id, access_token, login_customer_id)
```

**What it does:**
- Converts asset IDs to actual text content
- Handles text assets only (images/videos ignored)

**Why separate queries:**
Google Ads API requires separate queries for performance vs. content data.

### STEP 3: CATEGORIZE ASSETS INTO TIERS
**Method:**
```python
_categorize_assets(performance_data, asset_details)
```

**Performance Tiers:**

| Tier | Labels | Purpose |
|------|--------|---------|
| **LOW** | `LOW` | Target for optimization |
| **Tier 1** | `GOOD`, `BEST` | Best examples for LLM |
| **Tier 2** | `LEARNING`, `PENDING` | Secondary examples |
| **Tier 3** | `UNSPECIFIED`, others | Fallback examples |

**Output structure:**
```python
{
    "low_assets": [...],
    "tier_1": [...],
    "tier_2": [...],
    "tier_3": [...]
}
```

### STEP 4: FIND SIMILAR ASSETS (SEMANTIC MATCHING)
**Method:**
```python
_find_similar_assets(low_asset_text, categorized_assets, asset_type, campaign_name, ad_group_name)
```

**5-Tier Fallback Strategy:**

#### Tier 1: GOOD/BEST Assets
```python
if tier_1_assets:
    # Use semantic similarity to find related high-performers
    return top_5_similar_assets, "tier_1"
```

**How it works:**
1. Generate embeddings for LOW asset text
2. Generate embeddings for all tier_1 assets
3. Calculate cosine similarity
4. Return top 5 matches above 0.7 threshold

**Why this is best:**
Direct examples of what's already working well.

#### Tier 2: LEARNING/PENDING Assets
```python
elif tier_2_assets:
    # Assets still gathering data
    return top_5_similar_assets, "tier_2"
```

**Why:**
These assets are newer but not yet labeled LOW - safer examples than tier_3.

#### Tier 3: Other Assets
```python
elif tier_3_assets:
    # Any non-LOW assets
    return top_5_similar_assets, "tier_3"
```

**Why:**
Better than no examples, even if performance is unspecified.

#### Tier 4: Campaign Context Keywords
**Method:**
```python
_extract_keywords(campaign_name, ad_group_name)
```

**What it does:**
```python
# Input
campaign_name = "Greenesto Primus - Brand Campaign - 07June 24"
ad_group_name = "Luxury Apartments Bangalore"

# Process
1. Combine: "greenesto primus brand campaign 07june 24 luxury apartments bangalore"
2. Extract words: ["greenesto", "primus", "brand", "campaign", "luxury", ...]
3. Remove stopwords: ["campaign", "the", "and", "group", ...]
4. Keep meaningful: ["greenesto", "primus", "luxury", "apartments", "bangalore"]
5. Return first 5 keywords

# Output
["greenesto", "primus", "luxury", "apartments", "bangalore"]
```

**Why this matters:**
When there are NO assets to learn from, campaign/ad group names provide critical context:

❌ Without keywords: Generic "Best Luxury Apartment in City"
✅ With keywords: Specific "Premium Greenesto Primus Apartments in Bangalore"

**Stopwords removed:**
```python
stopwords = {
    "campaign", "ad", "group", "adgroup", 
    "the", "a", "an", "and", "or", "but",
    "in", "on", "at", "to", "for"
}
```

**Usage in prompt:**
```
Campaign Context:
- Keywords: greenesto, primus, luxury, apartments, bangalore
```

#### Tier 5: General Best Practices
```python
else:
    # No assets, no keywords - pure LLM knowledge
    return [], "general_best_practices"
```

**Why:**
Last resort - relies entirely on LLM's knowledge of ad copy best practices.

### STEP 5: GENERATE SUGGESTIONS VIA LLM
**Method:**
```python
_generate_suggestions(low_asset, similar_assets, source_tier, campaign_name, ad_group_name)
```

**LLM Prompt Structure:**

The prompt adapts based on available data:

**With Examples (Tier 1-3):**
```
You are optimizing a LOW-performing {HEADLINE/DESCRIPTION}.

Campaign: "Greenesto Primus Campaign"
Current LOW asset: "Old Generic Headline"

High-performing examples:
1. "Premium Greenesto Primus Luxury Apartments"
2. "Exclusive Bangalore Living at Primus"
...

Generate 3 better alternatives (20-30 chars).
```

**With Keywords Only (Tier 4):**
```
You are optimizing a LOW-performing {HEADLINE/DESCRIPTION}.

Campaign: "Greenesto Primus Campaign"
Current LOW asset: "Old Generic Headline"

Campaign Keywords: greenesto, primus, luxury, apartments, bangalore

Generate 3 better alternatives using these keywords.
```

**No Context (Tier 5):**
```
You are optimizing a LOW-performing {HEADLINE/DESCRIPTION}.

Current LOW asset: "Old Generic Headline"

Generate 3 industry best-practice alternatives.
```

**LLM Response Format:**
```json
[
    "Greenesto Primus Luxury Homes",
    "Premium Bangalore Apartments",
    "Exclusive Primus Living"
]
```

### STEP 6: VALIDATE SUGGESTIONS
**Method:**
```python
_validate_suggestions(suggestions, asset_type)
```

**Validation Rules:**

1. **Character Limits:**
   - Headlines: 30 chars max
   - Descriptions: 90 chars max

2. **Deduplication:**
   - Remove exact duplicates
   - Case-insensitive matching

3. **Quality Checks:**
   - Non-empty strings
   - Proper trimming

**Example:**
```python
# Input
suggestions = [
    "Premium Greenesto Apartments Bangalore",  # 39 chars ❌ TOO LONG
    "Greenesto Luxury Living",                  # 24 chars ✅
    "Greenesto Luxury Living",                  # Duplicate ❌
    "Primus Premium Homes"                      # 20 chars ✅
]

# Output (for HEADLINE)
validated = [
    "Greenesto Luxury Living",
    "Primus Premium Homes"
]
```

### STEP 7: FORMAT OUTPUT
**Final structure:**
```json
{
    "suggestions": [
        {
            "id": "144066891891",
            "type": "HEADLINE",
            "text": "Old Headline",
            "label": "remove",
            "reason": "LOW performance (0 impressions)",
            "ad_group_id": "123456",
            "ad_id": "789012",
            "campaign_id": "21367850110",
            "based_on": "tier_1"
        },
        {
            "id": null,
            "type": "HEADLINE",
            "text": "Greenesto Luxury Living",
            "label": "add",
            "reason": "Replacement for LOW asset",
            "ad_group_id": "123456",
            "ad_id": "789012",
            "campaign_id": "21367850110",
            "replaces_asset_id": "144066891891",
            "based_on": "tier_1"
        }
    ]
}
```

**Why this format:**
- **Flat structure**: Easy to process programmatically
- **add/remove labels**: Clear action items
- **Context included**: ad_group_id, ad_id, campaign_id for direct application
- **Traceability**: `based_on` shows which tier generated the suggestion

## API ENDPOINTS

### Single Campaign Analysis
```
POST /api/v1/optimization/analyze-campaign
```

**Request:**
```json
{
    "customer_id": "4220436668",
    "campaign_id": "21367850110",
    "login_customer_id": "4679708549"
}
```

### Bulk Campaign Analysis
```
POST /api/v1/optimization/analyze-all-campaigns
```

**Request:**
```json
{
    "customer_id": "4220436668",
    "login_customer_id": "4679708549"
}
```

**Features:**
- Processes campaigns in parallel (asyncio)
- Continues on individual failures
- Returns success/failure breakdown

## PAGINATION HANDLING

**Campaign Fetching:**
```python
# Handles multiple pages automatically
while True:
    response = fetch_page(page_token)
    campaigns.extend(response['results'])
    
    page_token = response.get('nextPageToken')
    if not page_token:
        break
```

**Why needed:**
Google Ads API paginates large result sets.

## ERROR HANDLING

**API Failures:**
- 403 Forbidden → Permission issues / wrong login_customer_id
- 401 Unauthorized → Invalid/expired access token
- 400 Bad Request → Invalid customer_id or campaign_id

**Service Failures:**
- No assets found → Returns empty suggestions
- LLM timeout → Skip that asset, continue with others
- Validation failures → Filter out invalid suggestions

## LOGGING

**Structured logs at every step:**
```json
{"step": "fetch_performance", "event": "Fetching asset performance data"}
{"step": "fetch_performance_complete", "total_results": 42}
{"step": "categorize_complete", "low_count": 5, "tier_1_count": 8}
{"step": "process_low_asset", "progress": "1/5", "asset_id": "12345"}
{"step": "find_similar_complete", "similar_count": 5, "source_tier": "tier_1"}
{"step": "generate_suggestions", "asset_id": "12345"}
{"step": "validate_complete", "validated_count": 3, "rejected_count": 1}
{"step": "analysis_complete", "total_suggestions": 15}
```

## PERFORMANCE CONSIDERATIONS

**Single Campaign:**
- Time: ~15-30 seconds
- API Calls: 2-3 (performance + text + metrics)
- LLM Calls: 1 per LOW asset

**Bulk Analysis (10 campaigns):**
- Time: ~3-5 minutes (parallel processing)
- API Calls: ~30-40
- LLM Calls: Varies by LOW asset count

## LIMITATIONS & FUTURE IMPROVEMENTS

**Current Limitations:**
- V1 processes synchronously (no background jobs)
- No database storage of suggestions
- No suggestion history tracking
- Manual application required

**Planned for V2:**
- Batch processing with Celery
- Database persistence
- Automated suggestion application
- Performance tracking over time
- Scheduled optimization runs
