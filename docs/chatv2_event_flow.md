# ChatV2 SSE Event Flow - Complete Reference

## Overview

ChatV2 uses a LangGraph state machine to orchestrate a multi-step campaign creation conversation. Each user message triggers a graph invocation that streams SSE events to the frontend. The graph **terminates** at pause points (account selection, location confirmation) and **re-enters** on the next message based on `ChatStatus`.

## Architecture

```
Frontend (SSE Client)
    |
    v
POST /api/ds/chatv2/stream?session_id=...
    |
    v
ChatV2Agent.process_message_stream()
    |
    +---> LangGraph.astream(stream_mode=["custom","messages","updates"])
    |         |
    |         +---> "custom"   --> nodes emit via get_stream_writer()
    |         +---> "messages" --> LLM token-by-token chunks
    |         +---> "updates"  --> state diffs after each node
    |
    +---> ScrapeTaskManager (concurrent asyncio task)
    |
    v
translate_stream_chunk() --> StreamEvent --> SSE wire format
```

### Three Stream Modes

| Mode | What it captures | Translator |
|------|-----------------|------------|
| `custom` | Node-emitted events via `get_stream_writer()` (progress, field_update, status) | `_handle_custom_event` |
| `messages` | LLM token chunks as `(AIMessageChunk, metadata)` tuples | `_handle_message_chunk` |
| `updates` | Full state diff after each node completes | `_handle_state_update` |

### Event Types

| Event | Purpose |
|-------|---------|
| `progress` | Step indicators: `{node, phase: start\|update\|end, label, message}` |
| `content` | LLM streaming tokens: `{token, node}` |
| `data` | Structured payloads: `field_update`, `website_summary`, `screenshot`, `summary_chunk`, `competitor_selection`, `analysis_complete`, `session_init` |
| `status` | State machine transitions: `{status, progress, node}` |
| `done` | End of graph invocation: full response payload |
| `error` | Error with `{message, code, recoverable}` |

---

## Complete Session Walkthrough (Real Captured Events)

This traces an actual session for a real estate campaign (Purva Atmosphere, Bangalore).

---

### Request 1: Initial Message (e.g. "hi")

**Graph path**: `_route_entry(IN_PROGRESS)` -> `collect_data` -> `END`

| Seq | Event | Type | Source | Notes |
|-----|-------|------|--------|-------|
| 1 | `progress(collect_data, start, "Collecting campaign details")` | progress | `_wrap_node` | Node wrapper auto-emits |
| 2-15 | `content(token="Let's"..."?")` | content | `messages` mode | LLM streams token by token |
| 16 | `progress(collect_data, end)` | progress | `_wrap_node` | |
| 17 | `content(full message)` | content | `messages` mode | **ISSUE: Full message re-emitted as single chunk** |
| 18 | `status(ChatStatus.IN_PROGRESS)` | status | `updates` mode | State diff after node |
| 19 | `done({status: "in_progress", reply: "...", collected_data: {}})` | done | `_emit_completion` | Graph complete |
| - | `: ` (heartbeat/close) | comment | SSE layer | Connection close marker |

**Status**: `IN_PROGRESS` -> stays `IN_PROGRESS`
**Collected fields**: none

---

### Request 2: User Sends URL

User: `"https://www.puravankara.com/residential/bengaluru/purva-atmosphere"`

**Graph path**: `collect_data` -> `END`

| Seq | Event | Type | Source | Notes |
|-----|-------|------|--------|-------|
| 1 | `progress(collect_data, start)` | progress | `_wrap_node` | |
| 2-48 | `content(tokens)` | content | `messages` | LLM streams response |
| 49 | `data(field_update, {websiteURL, valid})` | data | `custom` | From `_process_tool_call` or `_fallback_url_extract` |
| 50 | `data(field_update, {websiteSummary, pending})` | data | `custom` | Background scrape kicked off |
| 51 | `progress(collect_data, end)` | progress | `_wrap_node` | |
| 52 | `content(full message again)` | content | `messages` | **DUPLICATE: full echo** |
| 53 | `data(field_update, {websiteURL, valid})` | data | `updates` | **DUPLICATE: from state diff** |
| 54 | `status(IN_PROGRESS)` | status | `updates` | |
| 55 | `done(...)` | done | agent | |
| 56-57 | `progress(scrape:cache_check, start/end)` | progress | post-done scrape | Cache hit - no full scrape needed |
| 58 | `data(website_summary, {full result})` | data | `_drain_buffered_scrape` | Cached scrape result merged |
| 59 | `data(analysis_complete, {business_name, summary, ...})` | data | agent | Summary card for frontend |

**Key behavior**: Scrape was a cache hit (previously analyzed URL), so full result arrives immediately after `done`. The `done` event fires FIRST to unblock user input.

**Status**: stays `IN_PROGRESS`
**Collected fields**: `websiteURL`

---

### Request 3: User Says "google" (Platform)

**Graph path**: `collect_data` -> `END`

| Seq | Event | Type | Source | Notes |
|-----|-------|------|--------|-------|
| 1-2 | `progress(scrape:cache_check, start/end)` | progress | scrape replay | **Replayed every request** |
| 3 | `progress(collect_data, start)` | progress | `_wrap_node` | |
| 4-54 | `content(tokens)` | content | `messages` | LLM talks about Purva Atmosphere, asks duration |
| 55 | `progress(collect_data, end)` | progress | `_wrap_node` | |
| 56 | `content(full message)` | content | `messages` | **DUPLICATE echo** |
| 57 | `data(field_update, {websiteURL})` | data | `updates` | **DUPLICATE: unchanged field re-emitted** |
| 58 | `status(IN_PROGRESS)` | status | `updates` | |
| 59 | `done(...)` | done | agent | |

**Observation**: LLM did NOT call `update_ad_plan` tool this turn. It inferred "google" but didn't save it. The `productName` was mentioned conversationally but not extracted via tool. This means `collected_data` in `done` still only shows `websiteURL`.

**Status**: stays `IN_PROGRESS`
**Collected fields**: `websiteURL` (only - platform/productName not saved yet)

---

### Request 4: User Says "2 months" (Duration)

**Graph path**: `collect_data` -> `END`

| Seq | Event | Type | Source | Notes |
|-----|-------|------|--------|-------|
| 1-2 | scrape cache_check replay | progress | | |
| 3 | `progress(collect_data, start)` | progress | | |
| 4-35 | `content(tokens)` | content | | LLM asks about leads/budget |
| 36 | `progress(collect_data, end)` | progress | | |
| 37 | `content(full message)` | content | | **DUPLICATE** |
| 38 | `data(field_update, {websiteURL})` | data | `updates` | **DUPLICATE: same field, every turn** |
| 39 | `status(IN_PROGRESS)` | status | | |
| 40 | `done(...)` | done | | |

**Same issue**: LLM said "60 days" conversationally but did NOT call the tool. `durationDays` not in `collected_data`.

**Status**: stays `IN_PROGRESS`
**Collected fields**: `websiteURL` (still only 1 field!)

---

### Request 5: User Provides Budget (+ LLM Bulk Saves)

User gives budget. LLM finally calls `update_ad_plan` with ALL fields at once.

**Graph path**: `collect_data` -> `confirm_location` -> `END`

| Seq | Event | Type | Source | Notes |
|-----|-------|------|--------|-------|
| 1-2 | scrape cache_check replay | progress | | |
| 3 | `progress(collect_data, start)` | progress | `_wrap_node` | |
| 4 | `progress(collect_data, update, "User provided budget 6000...")` | progress | `_emit_reasoning` | LLM reasoning from tool args |
| 5-8 | `data(field_update, {platform\|productName\|budget\|durationDays})` | data | `custom` | From `_process_tool_call` - valid fields |
| 9-10 | `data(field_update, {websiteURL\|websiteSummary:pending})` | data | `custom` | URL re-extracted + pending scrape |
| 11 | `progress(collect_data, update, "All details collected!")` | progress | node | Transition signal |
| 12 | `progress(collect_data, end)` | progress | `_wrap_node` | |
| 13 | `content(full message)` | content | `messages` | "Got it! Setting up your Google campaign..." |
| 14-18 | `data(field_update, {websiteURL\|platform\|productName\|budget\|durationDays})` | data | `updates` | **DUPLICATE: all fields again from state diff** |
| 19 | `status(SELECTING_PARENT_ACCOUNT)` | status | `updates` | State transition |
| 20 | `progress(confirm_location, start)` | progress | `_wrap_node` | **Graph continues to next node** |
| 21 | `progress(confirm_location, start, "Checking business location")` | progress | node | **DUPLICATE start** |
| 22 | `progress(confirm_location, end, "Location review")` | progress | node | |
| 23 | `progress(confirm_location, end)` | progress | `_wrap_node` | **DUPLICATE end** |
| 24 | `content("We couldn't detect a property location...")` | content | `messages` | |
| 25-30 | `data(field_update, {all fields + businessType})` | data | `updates` | **DUPLICATE: entire ad_plan re-emitted** |
| 31 | `status(CONFIRMING_LOCATION)` | status | `updates` | |
| 32 | `done({status: "confirming_location", location_selection: {map_url: ...}})` | done | agent | **PAUSE POINT** |

**This is the critical turn**: LLM saved 4 fields at once, graph flowed through `collect_data` -> `confirm_location` in one invocation. Location not found in scrape, so map shown with India center coordinates.

**Status**: `IN_PROGRESS` -> `SELECTING_PARENT_ACCOUNT` -> `CONFIRMING_LOCATION`
**Collected fields**: websiteURL, platform, productName, budget, durationDays, businessType

---

### Request 6: User Sends Location Pin

User: `{"type": "location_update", "lat": 12.8673, "lng": 77.5868}`

**Graph path**: `_route_entry(CONFIRMING_LOCATION)` -> `confirm_location` -> `fetch_parent_account` -> `fetch_account` -> `END`

| Seq | Event | Type | Source | Notes |
|-----|-------|------|--------|-------|
| 1-2 | scrape cache_check replay | progress | | |
| 3 | `progress(confirm_location, start)` | progress | `_wrap_node` | |
| 4 | `progress(confirm_location, start, "Processing location")` | progress | node | |
| 5 | `progress(confirm_location, end)` | progress | `_wrap_node` | |
| 6 | `content("Location saved (12.8673, 77.5868)...")` | content | `messages` | |
| 7-13 | `data(field_update, {all fields + location})` | data | `updates` | **DUPLICATE: full ad_plan** |
| 14 | `status(SELECTING_PARENT_ACCOUNT)` | status | `updates` | |
| 15 | `progress(fetch_parent_account, start)` | progress | `_wrap_node` | **Continues** |
| 16 | `progress(fetch_parent_account, start, "Finding your Google Ads accounts")` | progress | node | |
| 17 | `progress(fetch_parent_account, end, "Auto-selected manager account: Modlix")` | progress | node | **Single MCC = auto-select** |
| 18 | `progress(fetch_parent_account, end)` | progress | `_wrap_node` | |
| 19-26 | `data(field_update, {all fields + loginCustomerId})` | data | `updates` | **DUPLICATE: entire ad_plan again** |
| 27 | `status(SELECTING_ACCOUNT)` | status | `updates` | |
| 28 | `progress(fetch_account, start)` | progress | `_wrap_node` | **Continues** |
| 29 | `progress(fetch_account, start, "Loading Google customer accounts")` | progress | node | |
| 30 | `progress(fetch_account, end, "Found 5 customer accounts")` | progress | node | Multiple = pause |
| 31 | `progress(fetch_account, end)` | progress | `_wrap_node` | |
| 32 | `status(SELECTING_ACCOUNT)` | status | `updates` | |
| 33 | `done({status: "selecting_account", account_selection: {5 options}, intermediate_messages: [location confirmed, MCC auto-selected]})` | done | agent | **PAUSE POINT** |

**Three nodes in one invocation**: `confirm_location` -> `fetch_parent_account` (auto-selected) -> `fetch_account` (5 options, pause). The `intermediate_messages` array carries the location confirmation and MCC auto-selection as breadcrumbs for the frontend.

**Status**: `CONFIRMING_LOCATION` -> `SELECTING_PARENT_ACCOUNT` -> `SELECTING_ACCOUNT`
**Collected fields**: + location, loginCustomerId

---

### Request 7: User Selects Account

User: `"4220436668"` (Fincity Common Ads)

**Graph path**: `_route_entry(SELECTING_ACCOUNT)` -> `select_account` -> `show_summary` -> `END`

| Seq | Event | Type | Source | Notes |
|-----|-------|------|--------|-------|
| 1-2 | scrape cache_check replay | progress | | |
| 3 | `progress(select_account, start)` | progress | `_wrap_node` | |
| 4 | `progress(select_account, start, "Selecting Google customer account")` | progress | node | |
| 5 | `progress(select_account, end, "Selected: Fincity Common Ads")` | progress | node | |
| 6 | `progress(select_account, end)` | progress | `_wrap_node` | |
| 7-15 | `data(field_update, {all fields + customerId})` | data | `updates` | **DUPLICATE: full ad_plan** |
| 16 | `status(AWAITING_CONFIRMATION)` | status | `updates` | |
| 17 | `progress(show_summary, start)` | progress | `_wrap_node` | |
| 18 | `progress(show_summary, end, "Awaiting confirmation")` | progress | node | |
| 19 | `progress(show_summary, end)` | progress | `_wrap_node` | |
| 20 | `content(campaign summary text)` | content | `messages` | Full summary with all fields |
| 21 | `done({status: "selecting_account", ...})` | done | agent | **Status OVERRIDDEN** (see below) |
| 22 | `data(competitor_selection, {8 competitors})` | data | `_merge_competitors_if_ready` | Post-done competitor data |

**Status override**: The graph sets `AWAITING_CONFIRMATION`, but `_build_response` detects `suggested_competitors` exist without confirmed `competitors`, so it overrides status to `selecting_account` to hold back the confirmation UI. The reply is also overridden to "Please review and select the competitors."

**Status**: `SELECTING_ACCOUNT` -> `AWAITING_CONFIRMATION` (internally) -> `selecting_account` (sent to frontend)
**Collected fields**: + customerId

---

### Request 8: User Confirms Competitors

User: `{"type": "competitor_selection", "competitors": ["Brigade Group", ...]}`

**Graph path**: SHORT-CIRCUITED (no graph invocation)

| Seq | Event | Type | Source | Notes |
|-----|-------|------|--------|-------|
| 1 | `progress(competitors, start, "Saving competitors")` | progress | `process_message_stream` | Handled before graph |
| 2 | `data(field_update, {competitors, [8 names]})` | data | agent | |
| 3 | `progress(competitors, end, "8 competitor(s) saved")` | progress | agent | |
| 4 | `done({status: "awaiting_confirmation", reply: summary, intermediate_messages: [confirmed_competitors]})` | done | agent | Final summary now visible |

**Special path**: `_try_parse_competitor_selection()` intercepts the JSON message BEFORE graph invocation. No LangGraph involved. The `_build_response` now sees `competitors` in ad_plan, so the hold-back logic no longer applies - full summary with `awaiting_confirmation` status is sent.

**Status**: `AWAITING_CONFIRMATION` (real this time)

---

## Event Source Matrix

Shows which source produces which event across the session:

| Event | `custom` (writer) | `messages` (LLM) | `updates` (state diff) | Agent (pre/post graph) |
|-------|:-:|:-:|:-:|:-:|
| progress(node, start) | x (node) + x (wrapper) | | | |
| progress(node, end) | x (node) + x (wrapper) | | | |
| progress(node, update) | x | | | |
| content(tokens) | | x (streaming) | | |
| content(full message) | | x (echo) | | |
| field_update (new field) | x | | x | |
| field_update (unchanged) | | | x | |
| status | | | x | |
| done | | | | x |
| scrape progress | | | | x |
| website_summary | | | | x |
| competitor_selection | | | | x |

---

## Duplicate Event Analysis

The `updates` stream mode causes significant duplication because it emits the FULL state diff after every node, which includes all ad_plan fields - not just changed ones.

### Duplicates Per Request

| Request | Unique Events | Duplicate Events | Ratio |
|---------|:---:|:---:|:---:|
| 1 (hi) | 18 | 1 (content echo) | 5% |
| 2 (URL) | 55 | 4 (1 content echo + 1 field_update + 2 scrape) | 7% |
| 3 (google) | 56 | 3 (1 content echo + 1 field_update + 1 status) | 5% |
| 4 (2 months) | 37 | 3 | 8% |
| 5 (budget - all fields) | 32 | ~14 (2x field_update per field + content echo + 2x progress per node) | 44% |
| 6 (location pin) | 33 | ~22 (3 nodes x full ad_plan re-emit) | 67% |
| 7 (account select) | 22 | ~12 (2 nodes x full ad_plan) | 55% |
| 8 (competitors) | 4 | 0 | 0% |

**The duplication problem scales with collected fields**: As more fields accumulate in `ad_plan`, every node transition re-emits ALL of them via `updates` mode. By request 6, there are 7+ fields x 3 node transitions = 21+ redundant field_update events.

### Double Progress Events

Every node gets TWO `start` and TWO `end` events:
1. `_wrap_node` emits `start` (generic)
2. Node itself emits `start` (with specific label)
3. Node emits `end` (with specific label)
4. `_wrap_node` emits `end` (generic)

---

## Critique & Suggestions

### Critical Issues

**1. `updates` stream mode causes O(fields x nodes) duplicate field_updates**

The `updates` mode emits the full `ad_plan` state diff after every node. Since `ad_plan` is a flat dict (not using a reducer), LangGraph treats the entire dict as "changed" whenever any node returns `ad_plan`. By request 6, this produces 20+ redundant `field_update` events per request.

**Fix options**:
- Remove `updates` from `stream_mode` entirely. The `custom` mode already emits field_updates for genuinely changed fields. The only thing `updates` adds is the `status` event, which could be emitted via `custom` instead.
- Or: add a dedup layer in `_handle_state_update` that tracks previously emitted field values and skips unchanged ones.

**2. Full message echo after streaming tokens**

After the LLM finishes streaming token-by-token (id:2-48), the `messages` mode emits one final chunk containing the FULL concatenated message (id:52). The frontend gets the message twice - once as tokens, once as a blob.

**Fix**: Filter out `AIMessageChunk` where content equals the already-streamed concatenation. Or check if the chunk is a "final" aggregation chunk (LangGraph behavior) and skip it.

**3. Double progress start/end per node**

`_wrap_node` and the node itself both emit `start` and `end`. The frontend sees:
```
progress(confirm_location, start, "Confirming location")     <- wrapper
progress(confirm_location, start, "Checking business location") <- node
progress(confirm_location, end, "Location review")           <- node
progress(confirm_location, end, "")                          <- wrapper
```

**Fix**: Remove progress emission from `_wrap_node` since every node already emits its own start/end with better labels. Or: have `_wrap_node` only emit if the node doesn't.

**4. Status string inconsistency**

`updates` mode emits `"ChatStatus.IN_PROGRESS"` (the enum repr), but `done` event emits `"in_progress"` (the value). Frontend must handle both formats.

**Fix**: In `_handle_state_update`, convert `status` to string value: `str(status.value) if hasattr(status, 'value') else str(status)`.

### Design Concerns

**5. Competitor flow uses status override hack**

When competitors are pending, `_build_response` overrides `AWAITING_CONFIRMATION` to `SELECTING_ACCOUNT` and replaces the reply text. This means the `status` event from `updates` mode says `AWAITING_CONFIRMATION` but the `done` event says `selecting_account`. Frontend sees conflicting signals.

**Suggestion**: Introduce a proper `SELECTING_COMPETITORS` status in `ChatStatus` enum. This makes the state machine explicit rather than relying on response-level overrides.

**6. LLM batches field extraction unpredictably**

In requests 3 and 4, the LLM acknowledges fields conversationally ("60 days", "google") but does NOT call `update_ad_plan`. It waits until request 5 to save everything at once. This means `collected_data` in `done` doesn't reflect what the user has actually provided - it only shows what the LLM has formally saved.

**Suggestion**: Consider a post-LLM extraction step that detects mentioned-but-unsaved fields, or adjust the system prompt to encourage incremental saves. Alternatively, emit "tentative" field_updates based on LLM conversation content even before tool calls.

**7. Scrape cache_check replays on every request**

The `_drain_buffered_scrape_events(replay_history=True)` call at the start of `process_message_stream` replays all historical scrape progress. For a cached scrape, this means `cache_check start/end` appears at the top of EVERY request after the URL is provided.

**Suggestion**: Only replay on SSE reconnect (when `Last-Event-ID` is provided), not on every new message.

**8. No explicit `session_init` in captured data**

The first request's captured events don't show `session_init`. The code in `api/chatv2.py` yields it before the graph stream, but the capture starts at id:1 with `progress(collect_data, start)`. This might mean the session was pre-created via `/start-session`, or the event was consumed before capture began.

### Suggestions for Improvement

**9. Add event deduplication layer**

A thin middleware between `translate_stream_chunk` and the SSE emitter could track `(event_type, field, value)` tuples and suppress duplicates within a single request cycle.

**10. Replace `updates` mode with explicit custom events**

Every useful signal from `updates` mode (status changes, new field values) is already available through `custom` mode or could be trivially added. Removing `updates` would eliminate the largest source of duplication.

**11. Structured `done` payload should include `intermediate_messages` timeline**

The `done` event packs `intermediate_messages` as a flat array, but the frontend needs to reconstruct the order (location confirmed -> MCC selected -> account selected). Adding a `sequence` or `timestamp` field would make reconstruction reliable.

**12. Consider separating graph events from scrape events into named SSE channels**

Currently both graph and scrape events share the same SSE stream with `node` prefixed as `scrape:*`. A cleaner separation (e.g., `event: scrape_progress` vs `event: graph_progress`) would let the frontend route them to different UI areas without parsing node names.

---

## State Machine Diagram

```
                    +--[IN_PROGRESS]--+
                    |                 |
                    v                 |
              collect_data            |
                    |                 |
           (all fields?) --NO------->+
                    |YES
                    v
           confirm_location
                    |
           (real estate?) --NO--> passthrough
                    |YES
                    v
           CONFIRMING_LOCATION [PAUSE]
                    |
              (user pins)
                    |
                    v
         fetch_parent_account
                    |
            (1 parent?) --YES--> auto-select
                    |NO                |
                    v                  v
    SELECTING_PARENT_ACCOUNT    fetch_account
           [PAUSE]                    |
              |                (1 account?) --YES--> auto-select
         (user selects)              |NO                |
              |                      v                  v
              +-----------> SELECTING_ACCOUNT      show_summary
                               [PAUSE]                 |
                                  |                    v
                            (user selects)    AWAITING_CONFIRMATION
                                  |                [PAUSE]
                                  v                    |
                            show_summary          (user confirms)
                                  |                    |
                                  v                    v
                        AWAITING_CONFIRMATION      COMPLETED
                             [PAUSE]
                                  |
                          (competitors found?)
                                  |YES
                                  v
                        [competitor selection - inline, no graph]
                                  |
                            (user confirms)
                                  |
                                  v
                          AWAITING_CONFIRMATION (real)
                                  |
                            (user confirms)
                                  |
                                  v
                             COMPLETED
```

## SSE Wire Format

```
id: {incrementing_seq}
event: {progress|content|data|status|done|error}
data: {"event":"<type>","data":{...},"id":null}

```

- Heartbeat: `: heartbeat\n\n` every 15s
- Close marker: `:\n\n`
- Reconnect: `Last-Event-ID` header replays from persistent store
