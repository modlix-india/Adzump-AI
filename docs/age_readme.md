# Age Optimization

The Age Optimization feature evaluates Google Ads performance across age ranges and generates recommendations for adding or removing age range targeting on ad groups to improve efficiency and ROI.

Recommendations are:
- **Metric-driven** — based on real impressions, clicks, conversions, and cost data from the last 30 days
- **LLM-assisted** — GPT-4o-mini analyzes performance per ad group and suggests ADD or REMOVE actions
- **Post-filtered** — strict validation ensures ADD only targets untargeted ranges, REMOVE only targets active ranges
- **Hallucination-resistant** — each LLM call receives only one ad group's data, minimizing cross-ad-group confusion

---

## API Endpoint

```
POST /api/ds/optimize/age
```

### Headers

| Header | Description |
|---|---|
| `Authorization` | `Bearer <access_token>` |
| `clientCode` | Client identifier used to scope the request |

---

## Processing Flow

```
API Request
  → AgeOptimizationAgent.generate_recommendations()
    → Fetch all accessible Google accounts
    → Get campaign → product mapping
    → For each account (parallel):
        → fetch_age_metrics()  ← fires PERFORMANCE_QUERY + TARGETING_QUERY in parallel
          → Merges is_targeted into each row
          → Injects synthetic rows for all 7 age ranges per ad group
        → Filter campaigns linked to a product
        → Rebuild targeting_map from merged rows
        → Group rows by ad_group_id
        → For each ad group (parallel):
            → Call GPT-4o-mini with that ad group's 7 rows
            → Parse recommendations
        → _filter_recommendations() — validate all ADD/REMOVE actions
        → Store results
```

---

## Components

### 1. Adapter — `adapters/google/optimization/age.py`

Handles all Google Ads API interactions. Key design decisions:

- **Class-level query constants** — `PERFORMANCE_QUERY` and `TARGETING_QUERY` are defined as class constants (easier to read and maintain)
- **Parallel fetch** — both queries fire simultaneously via `asyncio.gather`
- **Account-level `TARGETING_QUERY`** — no campaign filter; fetches all age targeting for the account and filters locally
- **`is_targeted` merged per row** — every output row has `is_targeted: true/false` embedded, so the LLM needs no separate context block
- **Synthetic row injection** — age ranges not in `age_range_view` (zero impressions, never served) are injected with zero metrics and `is_targeted` derived from the targeting map, ensuring all 7 age ranges are always visible to the LLM

**`fetch_age_metrics()`** — the single public method. Returns a flat list of rows, one per (ad_group, age_range) pair:

| Field | Description |
|---|---|
| `campaign_id`, `campaign_name`, `campaign_type` | Campaign metadata |
| `ad_group_id`, `ad_group_name` | Ad group metadata |
| `age_range` | e.g. `AGE_RANGE_18_24` |
| `is_targeted` | `true` = ENABLED in Google Ads, `false` = not enabled |
| `resource_name` | Criterion resource name (only when `is_targeted: true`) |
| `calculated_metrics` | CTR, CPA, CPC, cost (zeros = never served) |

GAQL queries:
```sql
-- PERFORMANCE_QUERY (age_range_view)
SELECT campaign.id, campaign.name, ad_group.id, ad_group.name,
       ad_group_criterion.age_range.type, ad_group_criterion.resource_name,
       metrics.impressions, metrics.clicks, metrics.conversions, metrics.cost_micros
FROM age_range_view
WHERE {duration_clause} AND campaign.status = 'ENABLED'
  AND ad_group.status = 'ENABLED' AND ad_group_criterion.status != 'REMOVED'

-- TARGETING_QUERY (ad_group_criterion) — account-level, no campaign filter
SELECT ad_group.id, ad_group_criterion.age_range.type, ad_group_criterion.status
FROM ad_group_criterion
WHERE ad_group_criterion.type = 'AGE_RANGE'
  AND ad_group_criterion.status IN ('ENABLED', 'PAUSED')
  AND campaign.status = 'ENABLED' AND ad_group.status = 'ENABLED'
```

### 2. Agent — `agents/optimization/age_optimization_agent.py`

Core orchestrator. Key responsibilities:

- **Per-ad-group LLM calls** — metrics are grouped by `ad_group_id` and each group gets its own parallel LLM call. This prevents cross-ad-group hallucination since the LLM only sees one `ad_group_id` at a time.
- **Error isolation** — `asyncio.gather(return_exceptions=True)` means a failed ad group call is logged and skipped; other ad groups still produce recommendations.
- **`targeting_map` rebuilt locally** — scanned from `is_targeted` fields in merged rows. No extra API call needed.
- **`resource_name` backfill** — before calling the LLM, a `(ad_group_id, age_range) → resource_name` map is built from the metrics rows. After parsing the LLM response, any REMOVE recommendation missing a `resource_name` is backfilled from this map. This ensures REMOVE operations always have the criterion ID needed to execute against the Google Ads API, even if the LLM omits it.
- **Strict post-LLM filter** — `_filter_recommendations()` enforces correctness independently of what the LLM said.

### 3. LLM Prompt — `prompts/optimization/age_optimization_prompt.txt`

The prompt receives **one ad group's data at a time** (7 rows — one per age range). The LLM reads `is_targeted` directly from each row:

```
is_targeted: true  → REMOVE if poor performance
is_targeted: false → ADD if strong product-audience fit
```

No separate text blocks for targeting state or untargeted ranges are needed — everything is self-contained in each row.

### 4. Models — `core/models/optimization.py`

- **`AgeFieldRecommendation`** — `ad_group_id`, `age_range`, `recommendation` (`ADD`/`REMOVE`), `resource_name`, `reason`
- **`OptimizationFields`** — container with `age: list[AgeFieldRecommendation]`
- **`CampaignRecommendation`** — top-level object with `campaign_id`, `account_id`, `product_id`, `fields`

---

## Filtering Logic

After each ad group's LLM call, `_filter_recommendations()` runs:

1. **Exclude `AGE_RANGE_UNDETERMINED`** from targeting checks — not a real targetable range
2. **Deduplicate** — drop any `(ad_group_id, age_range, recommendation)` duplicate
3. **Filter ADDs** — drop ADD if the range is already in `targeting_map[ad_group_id]`
4. **Filter REMOVEs** — drop REMOVE if the range is not in `targeting_map[ad_group_id]`
5. **All-REMOVE guard** — if valid REMOVEs would remove every currently targeted range with no valid ADDs, skip the entire ad group

---

## API Call Efficiency

| Stage | Calls |
|---|---|
| Fetch accounts | 1 |
| `fetch_age_metrics()` per account | **2 in parallel** (PERFORMANCE + TARGETING) |
| LLM calls per ad group | 1 per ad group (all parallel) |

For an account with 10 linked campaigns and 3 ad groups each: **2 API calls + 30 parallel LLM calls** (vs the old approach of 2 sequential API calls + 1 large LLM call prone to hallucination).

---

## Failure Handling

| Scenario | Behavior |
|---|---|
| Campaign has no age data | Skipped — no rows returned from `age_range_view` |
| Campaign not linked to a product | Skipped — filtered by `campaign_mapping_service` |
| One ad group's LLM call fails | Logged, skipped — other ad groups still processed |
| Google Ads API error | Exception logged, account returns empty list |

---

## Example Output

```json
{
  "platform": "GOOGLE",
  "account_id": "4220436668",
  "campaign_id": "23085457578",
  "campaign_name": "Winter Sale Campaign",
  "fields": {
    "age": [
      {
        "ad_group_id": "195048573508",
        "ad_group_name": "Shoes - Broad",
        "age_range": "AGE_RANGE_18_24",
        "recommendation": "REMOVE",
        "resource_name": "customers/123/adGroupCriteria/456~789",
        "reason": "Zero impressions over 30 days — inactive audience segment"
      },
      {
        "ad_group_id": "195048573508",
        "ad_group_name": "Shoes - Broad",
        "age_range": "AGE_RANGE_35_44",
        "recommendation": "ADD",
        "reason": "Not currently targeted. Product targets professionals — strong demographic fit."
      }
    ]
  }
}
```
