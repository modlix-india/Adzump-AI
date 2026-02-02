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

> [!NOTE]
> If the campaign has **no keywords**, the service exits early with a `no_data` status.

---

## Step 3: Performance Classification

The `KeywordPerformanceClassifier` analyzes the fetched keywords to separate winners from losers.

- **Good Performers**: Keywords meeting thresholds for CTR, Conversion Rate, and CPL.
- **Poor Performers**: Keywords failing thresholds (e.g., Low Quality Score, High CPL).
- **Critical Failures**: Keywords with high click volume but 0 conversions are flagged specifically.

> [!IMPORTANT]
> If **no good keywords** are found, the service cannot determine a successful "theme" and will stop here, returning only the performance classification without new suggestions.

---

## Step 4: Strategic Theme Extraction

The service identifies the top 20% of the "Good Performers" to act as a seed for discovery. These keywords represent what is currently working for the user.

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

Keywords were analyzed, and new, high-scoring suggestions were found.

```json
{
  "status": "success",
  "campaign_id": "...",
  "total_keywords": 50,
  "good_keywords": [...],
  "poor_keywords": [...],
  "suggestions": [...],
  "suggestions_count": 10
}
```

### Case B: No Good Keywords

Campaign exists, but no keywords are performing well enough to base new ideas on.

```json
{
  "status": "success",
  "message": "No good keywords found to base suggestions on",
  "poor_keywords": [...]
}
```

### Case C: System Error

A failure occurred in external APIs (Google/OpenAI) or network.

```json
{
  "status": "error",
  "error": "Timeout during OpenAI analysis"
}
```

---

## Testing the Service (cURL)

You can test the endpoint manually using the following `curl` command. Replace the placeholders with your actual credentials and IDs.

```bash
curl -X POST "http://localhost:8000/api/ds/ads/keywords/analyze-update" \
     -H "Content-Type: application/json" \
     -H "clientCode: YOUR_CLIENT_CODE" \
     -H "access-token: YOUR_ACCESS_TOKEN" \
     -d '{
           "customer_id": "1234567890",
           "login_customer_id": "0987654321",
           "campaign_id": "1122334455",
           "data_object_id": "obj_testing_123",
           "duration": "LAST_30_DAYS",
           "include_negatives": false,
           "include_metrics": true
         }'
```

> [!TIP]
> Ensure your server is running and the `access-token` is valid for the Google Ads account.
