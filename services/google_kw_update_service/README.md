# Google Keywords Update Service: Step-by-Step Logic Guide

This document provides a detailed, step-by-step technical walkthrough of the `GoogleAdsKeywordUpdateService`. It explains how the service processes a request, the logic applied at each stage, and the potential outcomes.

---

## Step 1: Service Entry & Initialization

The process begins by importing the service and the required request model.

**Imports & Initialization:**

```python
from third_party.google.models.keyword_model import UpdateKeywordsStrategyRequest
from services.google_kw_update_service.google_keywords_update_service import GoogleAdsKeywordUpdateService

# Entry point for the service
service = GoogleAdsKeywordUpdateService()
```

**The Call:**
The service is called with a `UpdateKeywordsStrategyRequest` object containing the `campaign_id` and `customer_id`.

---

## Step 2: Concurrent Data Gathering

Once triggered, the service identifies the campaign and concurrently fetches two critical datasets using the `KeywordDataProvider`.

1.  **Campaign Keywords**: Fetches all existing keywords and their metrics (Impressions, Clicks, Conversions, CPL).
2.  **Business Context**: Fetches USPs, product summaries, and website URLs from internal storage.

> [!TIP]
> This stage uses `asyncio.gather` with `return_exceptions=True` to fetch both datasets in parallel, cutting initial latency by ~50%. If the campaign has **no keywords**, the service exits early with a `no_data` status.

---

## Step 3: Performance Classification

The `KeywordPerformanceClassifier` analyzes the fetched keywords using **strict, data-driven rules** to separate winners from losers and protect ad spend.

### Classification Rules

Keywords are evaluated against multiple criteria. A keyword is marked as **POOR** if it meets **2 or more criteria** OR triggers a **critical failure**.

#### Critical Failures (Immediate Poor Classification)

1.  **High Spend, Zero Conversions**
    - Threshold: `cost >= ₹2,000` AND `conversions = 0`
    - Reason: Budget drain with no ROI
    - Example: "sarjapur villas" - ₹5,137 spent, 0 conversions

2.  **Extreme Click Volume, Zero Conversions**
    - Threshold: `clicks >= 50` AND `conversions = 0`
    - Reason: Massive engagement failure
    - Rare in practice, but critical when it occurs

#### Standard Poor Performance Indicators

3.  **Low Click-Through Rate (CTR)**
    - Threshold: `CTR < 2.0%`
    - Reason: Ad copy or keyword relevance issue
    - Industry standard for search campaigns

4.  **Zombie Keywords (Impressions Without Clicks)**
    - Threshold: `impressions > 0` AND `clicks = 0`
    - Reason: Wasting impression share, not attracting users
    - Example: "villa for sale in bangalore sarjapur road" - 1 impression, 0 clicks

5.  **Low Quality Score**
    - Threshold: `quality_score <= 4`
    - Reason: Google's signal that keyword-ad-landing page alignment is poor
    - Higher threshold (4 vs. industry 3) for stricter quality control

6.  **No Conversions Despite Engagement**
    - Threshold: `clicks >= 15` AND `conversions = 0`
    - Reason: 15 clicks is statistically significant for real estate (long sales cycle)
    - Balances giving keywords a fair chance vs. protecting budget

7.  **High Cost Per Lead (CPL)**
    - Threshold: `CPL > 1.5x median CPL`
    - Reason: Inefficient spend compared to campaign average
    - Only flagged if not already marked for zero conversions

8.  **Low Conversion Rate**
    - Threshold: `conv_rate < 1.0%` AND `clicks >= 15`
    - Reason: Consistent underperformance in converting clicks to leads

> [!IMPORTANT]
> **Why 15 clicks?** Real estate has a long sales cycle. Users research for weeks before converting. Setting the threshold too low (e.g., 5 clicks) would prematurely flag keywords that might convert later. Industry data shows 15-20 clicks is the sweet spot for high-ticket items.

### Classification Outcomes

- **Good Keywords**: Meet performance thresholds, eligible for optimization
- **Poor Keywords**: Flagged with specific reasons (e.g., "Low CTR (1.2%)", "No clicks after 9 impressions")
- **Top Performers**: Top 20% of good keywords, used as seeds for new suggestions

> [!TIP]
> If **no good keywords** are found, the service cannot determine a successful "theme" and will stop here, returning only the performance classification without new suggestions.

---

---

## Step 4: Strategic Seed Selection

The service determines the "seeds" used to discover new keyword ideas from the Google Ads API.

### Default Mode (Feature Flag OFF)

The service uses **all good keywords** as seeds. This ensures that the discovery phase is grounded in real, proven performance data from the current campaign.

### Enhanced Mode (Feature Flag ON)

If `ENABLE_ENHANCED_SEED_EXPANSION` is enabled, the service triggers a multi-layer discovery pipeline:

1.  **LLM Seed Expansion**: Uses the business context and current performing keywords to generate 10 creative, high-intent variations.
2.  **Google Autocomplete Expansion**: Takes both the real keywords and LLM variations and fetches real-time search patterns from the Google Autocomplete API.
3.  **Cross-Source Deduplication**: Merges and cleans the seed list to remove redundancies.
4.  **Market Validation**: Sends the expanded, multi-layer seed list to the Google Ads API to fetch real search volume and competition data.

> [!TIP]
> Enhanced mode is ideal for campaigns with very few good keywords, as it uses AI and search patterns to "brainstorm" new entry points before validating them against actual Google Ads market data.

---

## Step 5: Suggestion Discovery (Google Ads API)

The service calls the Google Ads API to "Generate Keyword Ideas" using:

- The **Seed Keywords** from Step 4.
- The **Business URL** from Step 2.
- Localized settings (Geography and Language).

This returns a raw list of potential new keywords.

---

## Step 6: Semantic & LLM Analysis

This is the multi-layered filter phase:

1.  **Semantic Similarity**: The `SemanticSimilarityScorer` uses **OpenAI Embeddings** to ensure the new suggestions "feel" like the top performers.
2.  **LLM Intent Filtering**: The `LLMKeywordAnalyzer` (GPT-4o) evaluates each suggestion against the **Business Context** to ensure they aren't just similar, but actually relevant and high-intent.

---

## Step 7: Final Multi-Factor Scoring

Every remaining suggestion is given a final weighted score based on:

- **Search Volume** (Higher is better)
- **Competition Index** (Lower is better)
- **Business Relevance** (Determined by LLM)
- **Semantic Score** (Theme alignment)

---

## Step 8: Result Delivery

The service concludes by returning a structured response.

### Case A: Full Success

Keywords were analyzed, and new, high-scoring suggestions were found. The response is wrapped in a standardized `success_response`.

```json
{
  "success": true,
  "data": {
    "status": "success",
    "campaign_id": "...",
    "suggestions": [...],
    "suggestions_count": 10
  },
  "error": null,
  "details": {}
}
```

### Case B: No Good Keywords

Campaign exists, but no keywords are performing well enough to base new ideas on.

```json
{
  "success": true,
  "data": {
    "status": "no_good_keywords",
    "message": "No good keywords found to base suggestions on",
    "poor_keywords": [...]
  }
}
```

### Case C: Fail-Fast Errors

Failures in external APIs (Google Ads, OpenAI) or missing credentials are caught by the **Global Exception Handler** and returned as a standardized `error_response`.

```json
{
  "success": false,
  "data": null,
  "error": "Google Ads API fetch failed",
  "details": {
    "reason": "Missing developer token"
  }
}
```

---

## Technical Architecture Highlights

### 1. Request-Scoped Context

The service uses `AuthContext` to access `client_code` and `login_customer_id` globally. This is populated automatically by the `AuthContextMiddleware`.

### 2. Standardized Exceptions

All errors inherit from `BaseAppException`:

- `GoogleAdsException`: Credential or API fetch errors.
- `AIProcessingException`: LLM or Embedding calculation errors.
- `StorageException`: Database or Business context errors.

### 3. Credential Hardening

The `KeywordDataProvider` uses a centralized helper to fetch and validate tokens, ensuring that neither the Developer Token nor the Access Token is missing before making an API call.

---

## Configuration & Tuning

All classification thresholds are centralized in [`config.py`](file:///Users/venkat/adzumpRepos/Adzump-AI/services/google_kw_update_service/config.py):

```python
# Classification Thresholds
CTR_THRESHOLD = 2.0                    # Minimum CTR (%)
QUALITY_SCORE_THRESHOLD = 4            # Maximum acceptable poor QS
MIN_CLICKS_FOR_CONVERSIONS = 15        # Clicks before expecting conversions
CONVERSION_RATE_THRESHOLD = 1.0        # Minimum conversion rate (%)
CRITICAL_CLICK_THRESHOLD = 50          # Extreme failure threshold
CRITICAL_COST_THRESHOLD = 2000.0       # Budget protection (₹)

# Enhanced Seed Expansion
ENABLE_ENHANCED_SEED_EXPANSION = False # Multi-layer discovery flag
LLM_SEED_COUNT = 10                    # Creative variations count
AUTOCOMPLETE_MAX_SUGGESTIONS = 5       # Max results per seed

### Industry Benchmarks (Sources)

- **CTR Threshold (2.0%)**: Real estate average CTR is 3.71% ([WordStream 2023 Benchmarks](https://www.wordstream.com/blog/ws/2016/02/29/google-adwords-industry-benchmarks))
- **Quality Score (≤4)**: Google recommends addressing keywords with QS below 5 ([Google Ads Help](https://support.google.com/google-ads/answer/6167118))
- **MIN_CLICKS_FOR_CONVERSIONS (15)**: Based on your campaign data showing low conversion frequency and real estate's long sales cycle

### Suggested Adjustments by Industry

These are **guidelines based on sales cycle length**, not hard benchmarks:

| Industry    | Typical Sales Cycle | Suggested MIN_CLICKS | Rationale                         |
| ----------- | ------------------- | -------------------- | --------------------------------- |
| E-commerce  | Hours to days       | 10-12                | Fast decision-making              |
| Real Estate | Weeks to months     | **15-20**            | High consideration, long research |
| B2B SaaS    | Days to weeks       | 15-25                | Multiple stakeholders             |
| Lead Gen    | Days                | 8-12                 | Lower ticket, faster conversion   |

> [!NOTE]
> These are starting points. **Use your own campaign data** to refine thresholds. If your average conversion happens at 25 clicks, adjust `MIN_CLICKS_FOR_CONVERSIONS` accordingly.

---

## Testing the Service (cURL)

> [!TIP]
> Ensure your server is running and the `access-token` is valid for the Google Ads account.

curl -X POST "http://127.0.0.1:8000/api/ds/ads/keywords/analyze-update" \
 -H "Content-Type: application/json" \
 -H "clientCode: YOUR_CLIENT_CODE" \
 -H "access-token: YOUR_ACCESS_TOKEN" \
 -d '{
"customer_id": "1234567890",
"login_customer_id": "0987654321",
"campaign_id": "1122334455",
"data_object_id": "obj_testing_123"
}'

```

```

```
