# Meta Carousel Ads — Creative Generation

**Status:** Design Phase — Not Implemented
**Team Stack:** Python · FastAPI · OpenAI API · Meta Graph API v22.0

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Carousel Ad Structure](#2-carousel-ad-structure)
3. [Current State vs Target State](#3-current-state-vs-target-state)
4. [Implementation Plan](#4-implementation-plan)
5. [Phase 1 — Models & Schemas](#5-phase-1--models--schemas)
6. [Phase 2 — Prompt Design](#6-phase-2--prompt-design)
7. [Phase 3 — Agent Logic](#7-phase-3--agent-logic)
8. [Phase 4 — API Routes](#8-phase-4--api-routes)
9. [Edge Cases & Error Handling](#9-edge-cases--error-handling)
10. [Key Design Decisions](#10-key-design-decisions)

---

## 1. Executive Summary

### What This Feature Does

Generates creative text (headlines, primary text, descriptions) for Meta Carousel ad cards. Each card gets its own headline, primary text, and optional description. Images are **not generated** — users upload them later from the UI. The payload builder (Meta API construction) is **out of scope** here; it runs after user reviews the generated creatives.

### Why Carousel

Carousel ads consistently outperform single-image ads for:
- Showcasing multiple products/features
- Telling a sequential story (problem → solution → proof → CTA)
- Higher engagement rates (swipeable format)
- Better CTR for e-commerce and SaaS

### Scope

| In Scope | Out of Scope |
|---|---|
| Card text generation (headlines, primary_text, descriptions) | Image generation / upload |
| CTA + destination URL generation | Meta API payload construction |
| Card sequence strategy (narrative arc) | Ad creation / orchestration |
| Pydantic models for carousel output | Post-review ad submission |
| Extend existing endpoint (no new route needed) | |

---

## 2. Carousel Ad Structure

### Logical Model

```
CarouselCreative
├── cards: [CarouselCard]          # 3–5 cards
│   ├── headline: str              # ≤ 40 chars (display), ≤ 255 chars (API)
│   ├── primary_text: str          # ≤ 125 chars (display), ≤ 2200 chars (API)
│   └── description: str | None    # ≤ 30 chars (display), ≤ 255 chars (API)
├── cta: CallToAction              # Global CTA for all cards
└── cta_url: str                   # Global destination URL
```

### Card Sequence Strategy

Cards follow a narrative arc:

| Position | Role | Example (SaaS) |
|---|---|---|
| Card 1 | Hook / Problem | "Manual reporting takes hours" |
| Card 2 | Solution Intro | "AI-powered dashboards" |
| Card 3 | Key Feature | "Real-time data sync" |
| Card 4 | Social Proof | "Trusted by 500+ teams" |
| Card 5 | CTA / Offer | "Start your free trial" |

---

## 3. Current State vs Target State

| Component | Current (IMAGE) | Target (CAROUSEL) |
|---|---|---|
| Models | `CreativeText`: 5 headlines, 5 primary_texts, 5 descriptions for 1 ad | `CarouselCard[]`: N cards, each with 1 headline, 1 primary_text, 1 description |
| Prompt | `creative_text.txt` — single ad with multiple asset variations | `carousel_text.txt` — sequenced N-card narrative |
| Agent | `MetaCreativeAgent.generate_payload()` (strategy → text) | `generate_carousel_payload()` — summary → cards directly, no strategy step |
| API route | `POST /creative/generate` (same) | `POST /creative/generate` with `creative_type` param |
| Images | Generated + uploaded automatically | Optional — user uploads from UI |

---

## 4. Implementation Plan

```
Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4
Models      Prompt      Agent        Routes
```

Only 4 phases. Payload builder and orchestration come later (separate work item).

---

## 5. Phase 1 — Models & Schemas

### File: `core/models/meta.py`

```python
class CarouselCard(BaseModel):
    headline: str = Field(..., max_length=255)
    primary_text: str = Field(..., max_length=2200)
    description: str | None = Field(None, max_length=255)

class LLMCarouselPayload(BaseModel):
    """Raw LLM output for carousel text generation."""
    cards: list[CarouselCard] = Field(..., min_length=3, max_length=5)
    cta: str
    cta_url: str | None = None

    @field_validator("cards")
    @classmethod
    def validate_card_count(cls, v):
        if len(v) < 3:
            raise ValueError("Carousel requires at least 3 cards")
        if len(v) > 5:
            raise ValueError("Carousel max 5 cards")
        return v
```

No changes to `CreativePayload` union — payload building is out of scope.

---

## 6. Phase 2 — Prompt Design

### File: `prompts/meta/carousel_text.txt`

```
You are a Meta Ads Carousel Creative Strategist.

Generate a {card_count}-card carousel ad sequence for the following business:

Business Summary:
{summary}

---

Task:

Generate a {card_count}-card carousel ad sequence following this narrative arc:
- Card 1 (Hook): Grab attention with the problem or opportunity
- Card 2 (Solution): Introduce how the business/product solves it
- Card 3+ : Continue the story (features, proof, benefits)
- Last Card (CTA): Clear call to action with urgency

For EACH card, provide:
1. headline (max 40 characters — punchy, benefit-driven)
2. primary_text (max 125 characters — the main body copy)
3. description (max 30 characters — supporting detail, optional)

Also provide a single global CTA from this list: {valid_ctas}

Return ONLY valid JSON. No markdown, no code fences:
{{
  "cards": [
    {{
      "headline": "string",
      "primary_text": "string",
      "description": "string | null"
    }}
  ],
  "cta": "",
  "cta_url": "string | null"
}}

---

## 7. Phase 3 — Agent Logic

### File: `agents/meta/creative_agent.py`

**New imports** (add to existing imports):

```python
from core.models.meta import LLMCarouselPayload, CarouselCard, CreativeType
```

Add to `MetaCreativeAgent`. Single-step generation — summary to cards directly,
no separate strategy step.

```python
async def generate_carousel_payload(
    self,
    session_id: str,
    card_count: int = 5,
) -> LLMCarouselPayload:

    if session_id not in sessions:
        raise BusinessValidationException("Session not found")

    summary = sessions[session_id].get("campaign_data", {}).get("business_summary")
    if not summary:
        raise BusinessValidationException("Missing business summary in session.")

    # Cache summary for potential image generation later
    sessions[session_id].setdefault("campaign_data", {})
    sessions[session_id]["campaign_data"]["business_summary"] = summary

    valid_ctas = get_valid_ctas(CampaignObjective.OUTCOME_LEADS, DestinationType.WEBSITE)

    text_raw = await chat_completion(
        [{"role": "user", "content": format_prompt(
            "meta/carousel_text.txt",
            summary=summary,
            card_count=card_count,
            valid_ctas=valid_ctas,
        )}]
    )
    text_json = json.loads(_extract_json(text_raw.choices[0].message.content))
    text_json["cta"] = normalize_cta(text_json.get("cta"))

    try:
        payload = LLMCarouselPayload(**text_json)
    except ValidationError as e:
        logger.error("Carousel payload validation failed", error=str(e), raw=text_json)
        raise AIProcessingException("Invalid carousel payload from LLM")

    return payload
```

Key patterns matching existing code:
- Reads summary from `sessions[session_id]` — not from `business_service`
- `chat_completion()` receives `[{"role": "user", "content": ...}]` format
- JSON extracted via `_extract_json()` + `json.loads()`
- CTA normalized via `normalize_cta()`
- Valid CTAs injected from model constants via `get_valid_ctas()`
- **No strategy step** — carousel generates cards + CTA directly from summary

---

## 8. Phase 4 — API Routes

### File: `core/models/meta.py`

Extend existing `CreativeGenerationRequest` to include carousel params:

```python
class CreativeGenerationRequest(BaseModel):
    destination_type: DestinationType
    creative_type: CreativeType = CreativeType.IMAGE     # new
    card_count: int | None = Field(None, ge=3, le=5)    # new: for carousel
```

### File: `api/meta.py`

Reuse the same `POST /creative/generate` endpoint — branch by `creative_type`:

```python
@router.post("/creative/generate")
async def generate_creative(
    body: CreativeGenerationRequest,
    session_id: str = Query(..., alias="sessionId")
):
    if body.creative_type == CreativeType.CAROUSEL:
        result = await meta_creative_agent.generate_carousel_payload(
            session_id=session_id,
            card_count=body.card_count or 5,
        )
    else:
        result = await meta_creative_agent.generate_payload(
            session_id=session_id,
            destination_type=body.destination_type
        )
    return success_response(data=result.model_dump(mode="json"))
```

No new endpoint needed. The existing `POST /creative/generate` handles both formats via a
`creative_type` field on the request body.

**Note on response shape**: IMAGE returns `LLMCreativeTextPayload` (fields: `text`, `image`),
CAROUSEL returns `LLMCarouselPayload` (fields: `cards`, `cta`, `cta_url`).
The frontend must branch on `creative_type` to interpret the response.

---

## 9. Edge Cases & Error Handling

| Scenario | Handling |
|---|---|
| LLM generates < 3 cards | Catch during Pydantic validation, retry with explicit instruction |
| LLM generates > 5 cards | Truncate to first 5, log warning |
| Card text exceeds display limits | Allow API limits (255/2200/255). Warn log. Don't block. |
| Duplicate headlines across cards | Deduplicate by appending suffix or regenerate |
| Destination URL missing | Use business website URL as fallback |
| CTA invalid / missing | Default to LEARN_MORE |
| Card count requested < 3 | Clamp to 3 |
| Card count requested > 5 | Clamp to 5 |

---

## 10. Key Design Decisions

1. **Separate prompt**: Carousel gets its own `carousel_text.txt` rather than branching `creative_text.txt`. Output structure is fundamentally different (N cards with 1 asset each vs 1 ad with 5 asset variations).

2. **Per-card text, shared CTA**: Each card has its own headline + primary_text + description. CTA and URL are global across all cards — simpler UX and matches Meta's common carousel pattern.

3. **Narrative sequencing**: Cards always follow a narrative arc (hook → solution → feature → proof → CTA). Strategy parameter controls the flavor, not the structure.

4. **No images in scope**: Images are purely optional. Users upload from the UI. The model has no image fields. This keeps the generation endpoint fast and decoupled.

5. **Payload builder deferred**: The Meta API payload construction (`child_attachments`, `object_story_spec`) is a separate concern. It runs only after the user has reviewed and approved the generated text. This is a future work item.

6. **Reuses existing patterns**: Agent inherits from the same base, uses the same `chat_completion()`, `format_prompt()`, and `BusinessService` pattern as all other Meta agents. No new infrastructure needed.
