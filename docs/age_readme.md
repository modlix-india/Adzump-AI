Age Optimization

The Age Optimization feature evaluates Google Ads performance across age ranges and recommends how ad groups should be adjusted to improve efficiency and ROI.

It highlights age groups that should be:

- Prioritized for higher spend
- Continued as-is
- Optimized for better performance
- Paused or excluded due to poor results

All recommendations are metric-driven, LLM-assisted, and validated for consistency.

---

API Endpoint -
POST /optimize/age

Headers

- clientCode
- loginCustomerId
- customerId

Query Parameters

- campaignId
- duration

---

API Request
→ Retrieve Age-Based Metrics
→ Compute Performance Indicators
→ LLM-Based Optimization Analysis
→ Schema Validation
→ Optimized JSON Output

---

1. API Controller – ads_api.py

- Accepts optimization requests
- Delegates processing to the service layer
- Returns validated responses

2. Optimization Service – age_optimization_service.py

- Fetches age metrics
- Calculates performance values
- Calls the LLM
- Parses and validates output
- Returns a safe fallback if no data exists

3. Google Ads Integration – third_party.age_service.py

- Executes GAQL queries on age_range_view
- Uses Google Ads searchStream API
- Retrieves impressions, clicks, conversions, and cost data
- Filters to enabled ad groups only

4. Metrics Engine – utils.metrics_utils.py

- Calculates performance metrics once:
- CTR (%)
- CPC
- CPA
- Cost (micros → currency)
- Prevents metric recalculation by the LLM

5. LLM Decision Logic
   Prompt File - age_optimization_prompt.txt

- LLM Responsibilities
- Interpret age-level performance metrics
- Apply optimization rules
- Assign each age group a clear action:
  - Prioritize
  - Continue
  - Optimize
  - Pause
  - Insufficient data

- Constraint
  - Output must be valid JSON only

---

Validation Layer

- Responses are validated using Pydantic models (models.age_model.py)
- Guarantees schema consistency
- Protects downstream consumers (UI, APIs)

---

Failure Handling

- Missing credentials → 401
- Google Ads errors → forwarded response
- Invalid LLM output → 500
- All failures are logged via structlog

---

Example Output

{
"campaigns": [
{
"campaign_id": "123",
"ad_groups": [
{
"ad_group_id": "456",
"optimized_ages": [
{
"age": "18-24",
"CTR": 12.3,
"CPC": 18.1,
"CPA": 42.5,
"recommendation": "Prioritize",
"is_optimized": true
}
]
}
]
}
]
}
