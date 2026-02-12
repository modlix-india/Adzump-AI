# Optimization Agents

All optimization agents share: `api/optimization.py` entry point, `CampaignRecommendation` model, parallel account processing, and `recommendation_storage_service` for persistence.

## Shared Components

| File | Purpose |
|------|---------|
| `api/optimization.py` | API routes (`/api/ds/optimize/{age,search-terms,keywords,locations}`) |
| `adapters/google/accounts.py` | Fetch accessible accounts for a client |
| `core/models/optimization.py` | `CampaignRecommendation`, `KeywordRecommendation`, `OptimizationFields` |
| `core/services/recommendation_storage.py` | Store recommendations, merge by origin |
| `core/services/metric_evaluator_config.py` | Shared thresholds config + `group_by_campaign()` |
| `core/services/metric_performance_evaluator.py` | Evaluate performance (good/poor/top) — used by keyword + search_term |
| `core/services/business_context_service.py` | Business metadata + features extraction (shared) |

---

## 1. Keyword Optimization

`POST /api/ds/optimize/keywords` → `KeywordOptimizationAgent`

### Flow

```mermaid
sequenceDiagram
    participant API
    participant AGT as KeywordOptimizationAgent
    participant KIS as KeywordIdeaService
    participant EXT as External APIs

    API->>AGT: generate_recommendations(client_code)

    par Phase 1
        AGT->>EXT: Fetch accounts
        AGT->>EXT: Campaign-product mapping
    end

    AGT->>EXT: Business context per unique product_id [LLM]

    loop Per Account (parallel)
        AGT->>EXT: Fetch keyword metrics [GAQL]
        AGT->>AGT: Evaluate → mark top performers → group by campaign

        loop Per Campaign (parallel)
            AGT->>AGT: Track A: review poor keywords [no LLM → PAUSE]

            AGT->>KIS: Track B: suggest_keywords()
            KIS->>EXT: Seed expand [LLM + Autocomplete]
            KIS->>EXT: Keyword Planner [Google Ads API]
            KIS->>EXT: Semantic scoring [Embeddings]
            KIS->>EXT: LLM select keywords [LLM]
            KIS->>EXT: Ad-group assignment [Embeddings]
            KIS->>KIS: Score + rank + deduplicate
            KIS-->>AGT: ADD recommendations

            AGT->>AGT: Merge PAUSE + ADD
        end
    end

    AGT->>AGT: Store all recommendations
    AGT-->>API: {recommendations}
```

### File Map

| File | Purpose |
|------|---------|
| `agents/optimization/keyword_optimization_agent.py` | Orchestrator — accounts, campaigns, Track A (PAUSE) |
| `core/keyword/idea_service.py` | Track B — seed expand → planner → score → LLM select → deduplicate |
| `core/keyword/scorer.py` | Semantic scoring, ad-group assignment, multi-factor scoring |
| `core/keyword/seed_expander.py` | LLM seed generation + Google Autocomplete expansion |
| `adapters/google/optimization/keyword.py` | Fetch keyword metrics via GAQL |
| `adapters/google/optimization/keyword_planner.py` | Google Keyword Planner API (generateKeywordIdeas) |
| `prompts/optimization/keyword_suggestion_prompt.txt` | LLM keyword selection prompt |

### Scoring

5-factor weighted score (min threshold: 40):

| Factor | Weight | Source |
|--------|--------|--------|
| Volume | 0.25 | Google Keyword Planner |
| Competition | 0.20 | Google Keyword Planner |
| Business relevance | 0.25 | LLM selection |
| Intent | 0.15 | LLM selection |
| Semantic similarity | 0.15 | Embeddings vs top keywords |

### LLM Calls Per Campaign

1. Seed expansion (gpt-4o-mini)
2. Keyword selection (gpt-4o-mini)
3. Embeddings x2 (semantic scoring + ad-group assignment)

Business context calls are shared across campaigns with same `product_id`.

### Anti-Hallucination

- LLM-selected keywords merged with original Google data (`{**llm, **google}`) — Google metrics overwrite LLM values
- Keywords not in Google suggestions are skipped
- Existing campaign keywords excluded via case-insensitive deduplication

### Old Flow

`services/google_kw_update_service/` — marked with TODO for removal. See `claudeplans/keyword_old_vs_new.md` for detailed comparison.

---

## 2. Search Term Optimization

`POST /api/ds/optimize/search-terms` → `SearchTermOptimizationAgent`

### Flow

```mermaid
sequenceDiagram
    participant API
    participant AGT as SearchTermOptimizationAgent
    participant ANA as SearchTermAnalyzer
    participant EXT as External APIs

    API->>AGT: generate_recommendations(client_code)

    par Phase 1
        AGT->>EXT: Fetch accounts
        AGT->>EXT: Campaign mapping with summary
    end

    loop Per Account (parallel)
        AGT->>EXT: Fetch search terms [GAQL]
        AGT->>AGT: Group by campaign

        loop Per Campaign
            Note over AGT: Skip if no business summary

            loop Per Search Term (parallel)
                AGT->>ANA: analyze_term(summary, term, metrics)

                ANA->>EXT: Brand relevancy check [LLM]
                par After brand check
                    ANA->>EXT: Configuration relevancy [LLM]
                    ANA->>EXT: Location relevancy [LLM]
                end

                alt Brand + Config both miss
                    ANA->>ANA: Mark as negative (no match)
                else
                    ANA->>EXT: Overall relevancy [LLM]
                end

                ANA->>ANA: Performance check [programmatic]
                ANA-->>AGT: {positive | negative} recommendation
            end

            AGT->>AGT: Split into keywords + negativeKeywords
        end
    end

    AGT->>AGT: Store all recommendations
    AGT-->>API: {recommendations}
```

### File Map

| File | Purpose |
|------|---------|
| `agents/optimization/search_term_optimization_agent.py` | Orchestrator — accounts, campaigns, term analysis |
| `core/search_term/analyzer.py` | Multi-step relevancy analysis (brand → config → location → overall → performance) |
| `adapters/google/optimization/search_term.py` | Fetch search terms via GAQL |
| `prompts/optimization/search_term/*.txt` | Relevancy check prompts (brand, configuration, location, overall) |

### Analysis Pipeline

Each search term goes through 5 checks:

| Check | Type | Purpose |
|-------|------|---------|
| Brand | LLM | Is it our brand, competitor, or generic? |
| Configuration | LLM | Does it match product/service config? |
| Location | LLM | Is it geographically relevant? (skipped for competitor brands) |
| Overall | LLM | Combined relevancy + intent stage + suggestion type |
| Performance | Programmatic | Cost per conversion vs threshold (₹4000) |

### LLM Calls Per Search Term

- 3-4 relevancy checks (brand + config + location + overall)
- Overall check skipped if both brand and config miss (early exit)

### Output

Recommendations split into:
- `keywords` — positive: high-relevancy terms to add as keywords
- `negativeKeywords` — negative: irrelevant terms to block

### Old Flow

`services/search_term_service.py` + `services/search_term_pipeline.py` — marked with TODO in `ads_api.py`.

---

## 3. Age Optimization

`POST /api/ds/optimize/age` → `AgeOptimizationAgent`

### Flow

```mermaid
sequenceDiagram
    participant API
    participant AGT as AgeOptimizationAgent
    participant EXT as External APIs

    API->>AGT: generate_recommendations(client_code)

    AGT->>EXT: Fetch accounts
    AGT->>EXT: Campaign-product mapping

    loop Per Account (parallel)
        AGT->>EXT: Fetch age metrics [GAQL]
        AGT->>AGT: Filter to linked campaigns

        AGT->>EXT: Analyze all metrics in single LLM call [LLM]
        EXT-->>AGT: CampaignRecommendation[] (ADD/REMOVE age ranges)
    end

    AGT->>AGT: Store all recommendations
    AGT-->>API: {recommendations}
```

### File Map

| File | Purpose |
|------|---------|
| `agents/optimization/age_optimization_agent.py` | Orchestrator — accounts, metrics, LLM analysis |
| `adapters/google/optimization/age.py` | Fetch age range metrics via GAQL |
| `prompts/optimization/age_optimization_prompt.txt` | LLM analysis prompt |

### How It Works

- Fetches age range performance (impressions, clicks, conversions, cost) per ad group
- Calculates derived metrics (CTR, CPA, CPC)
- Sends all metrics to LLM in a single call → LLM returns structured `CampaignRecommendation[]`
- Recommendations: ADD (target underserved age ranges) or REMOVE (exclude poor-performing ones)

### LLM Calls Per Account

- 1 call with all campaign metrics (gpt-4o-mini)

### Old Flow

`services/age_optimization_service.py` — marked with TODO in `ads_api.py`.

---

## 4. Location Optimization

`POST /api/ds/optimize/locations` → `LocationOptimizationAgent`

### Flow

```mermaid
sequenceDiagram
    participant API
    participant AGT as LocationOptimizationAgent
    participant ADP as GoogleLocationAdapter
    participant EVL as LocationEvaluator
    participant EXT as Google Ads API

    API->>AGT: generate_recommendations(client_code)

    AGT->>EXT: Fetch accounts

    loop Per Account (parallel)
        AGT->>ADP: fetch_campaign_location_targets() [GAQL]
        AGT->>ADP: fetch_location_performance() [GAQL]
        AGT->>ADP: fetch_geo_target_details() [GAQL]

        loop Per Campaign
            AGT->>EVL: evaluate_campaign(targeted_locations, metrics, details)
            EVL->>EVL: Apply thresholds → ADD or REMOVE
            EVL-->>AGT: LocationRecommendation[]
        end
    end

    AGT->>AGT: Store all recommendations
    AGT-->>API: {recommendations}
```

### File Map

| File | Purpose |
|------|---------|
| `agents/optimization/location_optimization_agent.py` | Orchestrator — accounts, campaigns, evaluation |
| `core/services/location_evaluator.py` | Rule-based evaluation (thresholds for ADD/REMOVE) |
| `adapters/google/optimization/location.py` | 3 GAQL queries: targets, performance, geo details |

### How It Works

- Fetches current location targets, last-30-day location performance, and geo target metadata (3 GAQL queries per account)
- `LocationEvaluator` applies purely programmatic thresholds — **zero LLM calls**
- Recommendations: ADD (target converting non-targeted locations) or REMOVE (exclude non-converting high-spend locations)
- ADD recommendations with unknown location names are filtered out

### Evaluation Thresholds

| Recommendation | Condition | Reason |
|----------------|-----------|--------|
| **REMOVE** | Targeted location with clicks ≥ 50, spend > ₹10, conversions = 0 | High spend & clicks but zero conversions |
| **ADD** | Non-targeted location with conversions > 0 | Conversions from non-targeted location |

### LLM Calls

None — entirely rule-based.

### Metrics Collected

Impressions, clicks, conversions, cost (INR), CTR (%), avg CPC (INR), CPL (INR), conversion rate (%).

---

## Architecture Overview

```mermaid
graph TD
    API[api/optimization.py] --> KW[KeywordOptimizationAgent]
    API --> ST[SearchTermOptimizationAgent]
    API --> AGE[AgeOptimizationAgent]
    API --> LOC[LocationOptimizationAgent]

    KW --> ACC[GoogleAccountsAdapter]
    ST --> ACC
    AGE --> ACC
    LOC --> ACC

    KW --> KWA[GoogleKeywordAdapter]
    KW --> EVL[MetricPerformanceEvaluator]
    KW --> BCS[BusinessContextService]
    KW --> KIS[KeywordIdeaService]

    KIS --> SE[SeedExpander]
    KIS --> KP[GoogleKeywordPlannerAdapter]
    KIS --> SCR[Scorer]

    ST --> STA[GoogleSearchTermAdapter]
    ST --> ANA[SearchTermAnalyzer]

    AGE --> AGA[GoogleAgeAdapter]

    LOC --> LCA[GoogleLocationAdapter]
    LOC --> LCE[LocationEvaluator]

    KW --> STR[RecommendationStorage]
    ST --> STR
    AGE --> STR
    LOC --> STR

    SE --> OAI[OpenAI / Embeddings]
    KIS --> OAI
    SCR --> OAI
    ANA --> OAI
    AGE --> OAI
    BCS --> OAI
```
