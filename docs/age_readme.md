# Age Optimization

The Age Optimization feature evaluates Google Ads performance across age ranges and generates recommendations for adding or removing age range targeting on ad groups to improve efficiency and ROI.

Recommendations are:
- **Metric-driven** — based on real impressions, clicks, conversions, and cost data from the last 30 days
- **LLM-assisted** — GPT-4o-mini analyzes performance and suggests ADD or REMOVE actions
- **Post-filtered** — strict validation ensures ADD only targets untargeted ranges, REMOVE only targets active ranges
- **Balanced** — a 1:1 replacement strategy prevents net loss of targeting coverage

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
  → AgeOptimizationAgent.run()
    → Fetch all accessible Google accounts (GoogleAccountsAdapter)
    → For each account (parallel):
        → Fetch age metrics (GoogleAgeAdapter.fetch_age_metrics)
        → Filter campaigns linked to a product (campaign_mapping_service)
        → Fetch current age targeting state (GoogleAgeAdapter.fetch_age_targeting)
        → Build LLM prompt with metrics + targeting state + product context
        → Call GPT-4o-mini for ADD/REMOVE recommendations
        → Filter & balance recommendations (_filter_and_balance_recommendations)
        → Store results (recommendation_storage_service)
```

---

## Components

### 1. API Layer — `api/optimization.py`

- Accepts `POST /api/ds/optimize/age`
- Delegates to `AgeOptimizationAgent.run()`
- Returns the list of `CampaignRecommendation` objects

### 2. Agent — `agents/optimization/age_optimization_agent.py`

The core orchestrator. Key responsibilities:

- **Parallel account processing** — all accessible accounts are processed concurrently via `asyncio.gather`
- **Campaign filtering** — only campaigns linked to a product (via `campaign_mapping_service`) are processed
- **Two-step data fetch** — metrics and targeting state are fetched separately for clarity
- **LLM context enrichment** — prompt includes performance metrics, current targeting state, untargeted ranges, and product summary
- **Post-LLM filtering** — `_filter_and_balance_recommendations()` enforces:
  - ADD only if the age range is **not** currently targeted
  - REMOVE only if the age range **is** currently targeted
- **1:1 replacement strategy** — if REMOVEs > ADDs, `_suggest_untargeted_ranges()` auto-suggests new ranges based on performance (adjacent to best performer, or fallback to next best untargeted range)

### 3. Google Ads Adapter — `adapters/google/optimization/age.py`

Handles all Google Ads API interactions:

- **`fetch_age_metrics()`** — queries `age_range_view` for impressions, clicks, conversions, and cost over the last 30 days. Only returns campaigns with actual activity (zero-spend campaigns are excluded automatically).
- **`fetch_age_targeting()`** — queries `ad_group_criterion` to get the current ENABLED age range targeting state per ad group, returning a `dict[ad_group_id → set[age_range]]`.

GAQL query used for metrics:
```sql
SELECT
  campaign.id, campaign.name,
  ad_group.id, ad_group.name,
  ad_group_criterion.age_range.type,
  ad_group_criterion.status,
  metrics.impressions, metrics.clicks,
  metrics.conversions, metrics.cost_micros
FROM age_range_view
WHERE segments.date DURING LAST_30_DAYS
  AND campaign.status = ENABLED
  AND ad_group.status = ENABLED
  AND ad_group_criterion.status != REMOVED
```

### 4. LLM Decision Logic — `prompts/optimization/age_optimization_prompt.txt`

The prompt provides the LLM with:
- Per-campaign, per-ad-group performance metrics
- Currently targeted age ranges
- Untargeted age ranges available to add
- Product context summary

The LLM outputs a JSON array of recommendations, each with:
- `ad_group_id`, `age_range`, `recommendation` (`ADD` or `REMOVE`), `reason`

### 5. Models — `core/models/optimization.py`

All recommendations are validated against Pydantic models:

- **`AgeFieldRecommendation`** — single age range action (`ad_group_id`, `age_range`, `recommendation`, `resource_name`, `reason`)
- **`OptimizationFields`** — container with `age: list[AgeFieldRecommendation]`
- **`CampaignRecommendation`** — top-level object with `campaign_id`, `account_id`, `product_id`, `fields`

---

## Filtering Logic

After the LLM responds, `_filter_recommendations()` runs the following steps in order:

1. **Exclude `AGE_RANGE_UNDETERMINED`** from the targeting map — it is not a real targetable range and cannot be added or removed meaningfully
2. **Deduplicate** — drop any recommendation with a duplicate `(ad_group_id, age_range, recommendation)` key
3. **Filter ADDs** — drop any ADD for a range already in `targeting_map[ad_group_id]` (it's already allowed)
4. **Filter REMOVEs** — drop any REMOVE for a range not in `targeting_map[ad_group_id]` (nothing to remove)
5. **All-REMOVE guard** — if the valid REMOVEs would remove every currently targeted range and there are no valid ADDs, skip the entire ad group to prevent zeroing out targeting

> **Why no 1:1 replacement?** Age range targeting in Google Ads is exclusionary — enabling a range means "don't exclude this group", not "target only this group". Auto-adding ranges to compensate for removals is a no-op when those ranges are already enabled, and produces incorrect recommendations when they aren't. The LLM's REMOVE suggestions are trusted directly after filtering.

---

## Failure Handling

| Scenario | Behavior |
|---|---|
| Campaign has no age data (new/zero-spend) | Skipped — `age_range_view` returns no rows |
| Campaign not linked to a product | Skipped — filtered out by `campaign_mapping_service` |
| LLM returns invalid JSON | Exception logged via `structlog`, account skipped |
| Google Ads API error | Exception propagated and logged |

---

## Example Output

```json
{
  "platform": "google_ads",
  "account_id": "4220436668",
  "campaign_id": "23085457578",
  "campaign_name": "Subha White Waters - Demand Gen 7 Oct 25",
  "fields": {
    "age": [
      {
        "ad_group_id": "195048573508",
        "age_range": "AGE_RANGE_18_24",
        "recommendation": "REMOVE",
        "reason": "Zero impressions and clicks over 30 days"
      },
      {
        "ad_group_id": "195048573508",
        "age_range": "AGE_RANGE_25_34",
        "recommendation": "ADD",
        "reason": "Adjacent to best-performing 35-44 range, untargeted"
      }
    ]
  }
}
```
