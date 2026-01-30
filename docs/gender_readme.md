Gender Optimization

The Gender Optimization feature analyzes Google Ads performance by gender and recommends how each ad group should be optimized.

It identifies which genders to:

- Prioritize
- Continue
- Optimize
- Pause / Exclude

Recommendations are data-driven, LLM-generated, and schema-validated.

---

API Endpoint - POST /optimize/gender

Required Inputs

Headers

- clientCode
- loginCustomerId
- customerId

Query Params

- campaignId
- duration

---

End-to-End Flow
API Request
↓
Fetch Gender Metrics (Google Ads)
↓
Calculate CTR / CPC / CPA
↓
LLM Optimization Logic
↓
Pydantic Validation
↓
Final JSON Response

---

Key Components

1. API Layer – ads_api.py

- Receives request
- Calls service layer
- Returns response
- Contains no business logic

2. Service Layer – gender_optimization_service.py

- Fetches metrics
- Calculates performance values
- Calls the LLM
- Parses and validates output
- Returns a safe fallback if no data exists

3. Google Ads Fetch – third_party.gender_service.py

- Uses gender_view GAQL query
- Calls Google Ads searchStream API
- Fetches impressions, clicks, conversions, and cost
- Considers only enabled ad groups

4. Metrics Calculation – utils.metrics_utils.py

- Calculates metrics once:
  - CTR (%)
  - CPC
  - CPA
  - Cost (micros → currency)
- LLM does not recalculate metrics

5. LLM Optimization

- Prompt File: gender_optimization_prompt.txt

Rule

- Output must be strict JSON only

Response Validation Models – models.gender_model.py

- LLM output is validated using Pydantic models to:
- Prevent malformed responses
- Enforce API contract
- Ensure frontend-safe data

---

Error Handling

- Missing credentials → 401
- Google Ads API error → propagated status
- LLM parsing error → 500
- All errors are logged using structlog

---

Sample Output -
{
"campaigns": [
{
"campaign_id": "123",
"ad_groups": [
{
"ad_group_id": "456",
"optimized_genders": [
{
"gender": "MALE",
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
