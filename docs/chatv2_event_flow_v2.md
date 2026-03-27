# ChatV2 Event Flow - Visual Guide

> Simple, visual explanation of how the chat system works end-to-end.

---

## The Big Picture

Think of ChatV2 like a **restaurant order system**:

```
Customer (Frontend)  -->  Waiter (API)  -->  Kitchen (LangGraph)  -->  Side Kitchen (Scrape)
     |                       |                     |                        |
     |   "I want pizza"      |                     |                        |
     |--------------------->|                     |                        |
     |                       |  Start cooking      |                        |
     |                       |-------------------->|                        |
     |                       |                     |  Also analyze website  |
     |                       |                     |----------------------->|
     |   "chopping onions"   |<-- progress --------|                        |
     |<---------------------|                     |                        |
     |   "adding cheese"     |<-- progress --------|                        |
     |<---------------------|                     |                        |
     |   "pizza ready!"      |<-- done ------------|                        |
     |<---------------------|                     |                        |
     |   "website analyzed"  |<--------------------------------- result ----|
     |<---------------------|                     |                        |
```

The key insight: **the kitchen (graph) and side kitchen (scrape) work in parallel**. The waiter streams updates from both to the customer as they happen.

---

## How a Single Request Works

Every time the user sends a message, this happens:

```
User sends message
       |
       v
  +-----------------+
  | 1. PRE-GRAPH    |  Before the graph runs:
  |  - Replay any   |  - Scrape history replayed (so UI stays in sync)
  |    scrape events |  - Competitor JSON intercepted (shortcut, no graph needed)
  +-----------------+
       |
       v
  +-----------------+
  | 2. GRAPH RUNS   |  LangGraph state machine executes:
  |  - May run 1-4  |  - Each node streams events as it works
  |    nodes in a   |  - Multiple nodes can chain in one request
  |    single pass  |  - Graph STOPS at pause points (needs user input)
  +-----------------+
       |
       v
  +-----------------+
  | 3. POST-GRAPH   |  After graph finishes:
  |  - done event   |  - Done fires FIRST (user can type immediately)
  |  - scrape tail  |  - Remaining scrape events stream after
  |  - competitors  |  - Competitor data merged if ready
  +-----------------+
```

---

## The State Machine (How the Chat Progresses)

The whole flow is a series of **rooms**. The user moves from room to room:

```
  ROOM 1                    ROOM 2                ROOM 3              ROOM 4
  --------                  --------              --------            --------
  Collecting                Location              Account             Confirmation
  Campaign Info             (real estate          Selection
                            only)

  "What's your URL?"                              "Pick your          "Here's your
  "Which platform?"         "Pin your property     MCC account"        campaign summary.
  "How long?"               on the map"           "Pick your           Confirm?"
  "Budget?"                                        ad account"

  [IN_PROGRESS]          [CONFIRMING_LOCATION]   [SELECTING_*]      [AWAITING_CONFIRMATION]
       |                        |                     |                    |
       | all fields collected   | user pins location  | user picks         | user says "yes"
       |----------------------->|-------------------->| accounts           |
                                                      |----------->------>|
                                                                          |
                                                                     [COMPLETED]
```

**Important**: The user doesn't always visit every room:
- Room 2 is **SKIPPED** if the business is NOT real estate
- Room 3 has **auto-select** - if there's only 1 account, it skips ahead automatically
- Between Room 3 and 4, there's an **inline competitor selection** (no room change)

---

## What Happens in Each Room

### Room 1: Collecting Info (`collect_data` node)

```
User says something
       |
       v
  +------------------+
  | LLM reads the    |  The AI figures out what info the user provided
  | user's message   |  and what's still missing
  +------------------+
       |
       v
  Does LLM call the update_ad_plan tool?
       |                    |
      YES                   NO
       |                    |
       v                    v
  Save fields to        LLM just responds
  ad_plan state         conversationally
       |                (field NOT saved yet!)
       |
       v
  Is URL in the saved fields?
       |           |
      YES          NO
       |           |
       v           |
  Kick off         |
  background       |
  website scrape   |
       |           |
       v           v
  All required fields collected?
       |                |
      YES               NO
       |                |
       v                v
  Move to Room 2     Stay in Room 1
  (or skip to 3)     (ask next question)
```

**Events the frontend sees:**

```
progress  -->  "Collecting campaign details"        (start)
content   -->  "Got" "it" "!" "Setting" "up" "..."  (LLM typing, word by word)
data      -->  field_update: platform = "google"     (field saved)
data      -->  field_update: budget = "6000"          (field saved)
data      -->  field_update: websiteSummary = pending  (scrape started)
progress  -->  "All details collected!"               (moving on)
progress  -->  end                                     (node done)
```

### Room 2: Location Confirmation (`confirm_location` node)

Only for **real estate** businesses. The system checks the scrape result for property coordinates.

```
  Is business real estate?
       |              |
      YES             NO
       |              |
       v              v
  Show map to       Pass through
  user with         (go straight
  detected pin      to Room 3)
       |
       v
  PAUSE - wait for user
       |
  User confirms or moves pin
       |
       v
  Save coordinates + resolve geo targets
       |
       v
  Move to Room 3
```

**What the user sees:**

```
  +----------------------------------+
  | "We found your property at       |
  |  Thanisandra, Bangalore"         |
  |                                  |
  |  [====== Google Map ======]      |
  |  [     with pin marker    ]      |
  |  [========================]      |
  |                                  |
  |  [Confirm]  [Adjust on map]     |
  +----------------------------------+
```

### Room 3: Account Selection (3 nodes working together)

```
  fetch_parent_account
       |
  How many MCC/manager accounts?
       |          |           |
      0           1          2+
       |          |           |
       v          v           v
    Error     Auto-select   PAUSE
    go back   (no pause!)   Show list to user
                 |                |
                 |          User picks one
                 |                |
                 v                v
          fetch_account (child accounts)
                 |
          How many ad accounts?
                 |          |           |
                0           1          2+
                 |          |           |
                 v          v           v
            No accounts  Auto-select   PAUSE
            go back to   (no pause!)   Show list to user
            parent list       |              |
                              |        User picks one
                              |              |
                              v              v
                        Move to Room 4
```

**Auto-select is key**: If there's only 1 option at any level, the system picks it automatically and chains to the next step. This means in one request, you might see:

```
location confirmed -> MCC auto-selected -> 5 accounts found -> PAUSE
(3 nodes ran in a single request!)
```

**Events during auto-select chain:**

```
progress --> "Finding your Google Ads accounts"     (start)
progress --> "Auto-selected manager: Modlix"        (end - auto picked!)
progress --> "Loading Google customer accounts"     (start - immediately chains)
progress --> "Found 5 customer accounts"            (end - multiple = pause)
done     --> account_selection: [5 options]         (frontend shows picker)
```

### Room 4: Confirmation (`confirm` + `show_summary` nodes)

```
  show_summary
       |
       v
  Build summary text from ad_plan
  "Platform: Google Ads, Budget: 6000..."
       |
       v
  PAUSE - show summary to user
       |
  Are there competitors to review?
       |              |
      YES             NO
       |              |
       v              v
  Show competitor   Wait for
  picker first      "yes" / edits
       |
  User picks
  competitors
       |
       v
  Now show summary for confirmation
       |
  User says "yes" / makes edits
       |              |
     "yes"          edits
       |              |
       v              v
  COMPLETED       Update fields,
                  re-show summary
```

---

## The Event Types Explained

Think of events like **text messages from the kitchen to the waiter**:

### `progress` - "I'm working on step X"

```
  { phase: "start", node: "collect_data", label: "Collecting campaign details" }
                    ...time passes...
  { phase: "update", node: "collect_data", message: "User wants Google Ads" }
                    ...time passes...
  { phase: "end",   node: "collect_data" }
```

Like a loading spinner: **start** = spinner appears, **update** = status text changes, **end** = spinner gone.

### `content` - "Here's what the AI is typing"

```
  { token: "Got" }
  { token: " it" }
  { token: "!" }
  { token: " Setting" }
  { token: " up" }
  ...
```

Letter-by-letter (actually word-by-word) LLM output. Like watching someone type in a chat.

### `data` (field_update) - "A form field was filled in"

```
  { field: "platform",    value: "google", status: "valid" }
  { field: "budget",      value: "6000",   status: "valid" }
  { field: "websiteURL",  value: "...",    status: "invalid", error: "Not a valid URL" }
  { field: "websiteSummary", value: "...", status: "pending" }  <-- scrape in progress
```

Three statuses: `valid` (saved), `invalid` (rejected with error), `pending` (processing).

### `data` (other types) - "Here's structured data for the UI"

```
  website_summary       -->  Full scrape result (business type, summary, location)
  analysis_complete     -->  Condensed card for the chat bubble
  screenshot            -->  Website screenshot URL
  summary_chunk         -->  Streaming summary tokens (like content but for scrape)
  competitor_selection  -->  List of suggested competitors for picker UI
  session_init          -->  New session created, here's the ID
  confirmed_location    -->  (via intermediate_messages) Location was pinned
  confirmed_account     -->  (via intermediate_messages) Account was selected
  confirmed_competitors -->  (via intermediate_messages) Competitors confirmed
```

### `status` - "The state machine moved"

```
  { status: "in_progress" }              -->  Room 1
  { status: "confirming_location" }      -->  Room 2
  { status: "selecting_parent_account" } -->  Room 3 (pick MCC)
  { status: "selecting_account" }        -->  Room 3 (pick ad account)
  { status: "awaiting_confirmation" }    -->  Room 4
  { status: "completed" }               -->  Done!
```

### `done` - "This request is complete"

The big envelope at the end. Contains EVERYTHING the frontend needs to render the current state:

```json
{
  "status": "selecting_account",
  "reply": "Pick an account:",
  "collected_data": { "websiteURL": "...", "platform": "google", ... },
  "progress": "2/3",
  "account_selection": { "type": "account", "options": [...] },
  "location_selection": null,
  "message_attachments": [],
  "intermediate_messages": [
    { "reply": "Location saved", "attachments": [{ "type": "confirmed_location" }] },
    { "reply": "Auto-selected Modlix", "attachments": [{ "type": "confirmed_account" }] }
  ]
}
```

**`intermediate_messages`** = breadcrumbs of what happened automatically during this request. The frontend can render these as small notification cards.

---

## The Scrape Side-Channel

Website analysis runs **in parallel** with the main chat. Here's how they interact:

```
Timeline:
=========

Request 2 (user sends URL):
  |
  |  MAIN CHANNEL                    SCRAPE CHANNEL
  |  ============                    ==============
  |  collect_data starts             scrape job created
  |  LLM streaming...               |
  |  field_update: websiteURL        |
  |  field_update: websiteSummary    |
  |    = "pending"                   |
  |  collect_data ends               |
  |  DONE event fires <----------   |
  |  (user can type now!)            |
  |                                  cache_check: hit!
  |  website_summary event <-------- result ready
  |  analysis_complete event         |
  |  CONNECTION CLOSES               done
  |
Request 3 (user says "google"):
  |
  |  scrape history replayed         (cache_check start/end)
  |  collect_data starts
  |  LLM now HAS scrape data
  |    in its context!
  |  ...
```

**Key design decision**: The `done` event fires BEFORE scrape finishes. This lets the user keep chatting immediately. Scrape results trickle in after `done` and update the sidebar.

If the scrape was cached (URL analyzed before), the result is instant - it arrives right after `done`.

---

## Pause Points vs Continuous Flow

```
PAUSE = graph ends, waits for next user message
CONTINUOUS = graph chains to next node automatically

Request 5 example (budget provided, real estate):
  collect_data ----CONTINUOUS----> confirm_location ----PAUSE
  (all fields)                     (show map, wait for pin)

Request 6 example (user pins location, 1 MCC, 5 accounts):
  confirm_location --CONTINUOUS--> fetch_parent --CONTINUOUS--> fetch_account --PAUSE
  (save pin)         (1 MCC,       (5 accounts,
                      auto-select)  show picker)
```

**The router decides**: When the graph starts, `_route_entry` checks the current `ChatStatus` to know which room to enter. When a node finishes, conditional edges check the NEW status to decide: continue or stop?

```python
# Simplified logic:
def should_continue_after_collect(status):
    if status == SELECTING_PARENT_ACCOUNT:  # all fields collected
        return "go to confirm_location"     # CONTINUOUS
    return "END"                            # PAUSE (still collecting)

def should_continue_after_location(status):
    if status == SELECTING_PARENT_ACCOUNT:  # location confirmed
        return "go to fetch_parent"         # CONTINUOUS
    return "END"                            # PAUSE (showing map)
```

---

## How `intermediate_messages` Work

When multiple nodes run in one request, the user needs to see what happened at each step. That's what `intermediate_messages` are for.

**Example**: Request 6 runs 3 nodes. The `done` event includes:

```
intermediate_messages: [
  {
    reply: "Location saved (12.86, 77.58). Setting up ad accounts.",
    attachments: [{ type: "confirmed_location", coordinates: {...} }]
  },
  {
    reply: "Found 1 manager account - auto-selected Modlix",
    attachments: [{ type: "confirmed_account", name: "Modlix", id: "446..." }]
  }
]
```

Frontend renders these as notification cards above the account picker:

```
  +------------------------------------------+
  |  Location confirmed                      |
  |  [map pin icon] 12.8673, 77.5868         |
  +------------------------------------------+
  |  Manager account auto-selected           |
  |  [check icon] Modlix (4461972633)        |
  +------------------------------------------+
  |                                          |
  |  Select your ad account:                 |
  |  ( ) Codename Lake and Bloom             |
  |  ( ) Fincity Common Ads                  |
  |  ( ) Modlix Dev                          |
  |  ( ) Raja Datta Share                    |
  |  ( ) Test customer                       |
  |                                          |
  +------------------------------------------+
```

---

## The Competitor Side-Quest

Competitors are found **in the background** (like scrape) and injected at the right moment:

```
                   Background                    Main Flow
                   ==========                    =========

Request 2:         scrape starts
                        |
Request 5:         scrape done -------> competitor_find starts
                                              |
                                              |         collect_data -> confirm_location
                                              |         (PAUSE for map)
Request 6:                                    |         location -> accounts
                                              |         (PAUSE for account picker)
Request 7:                              competitors     account selected -> show_summary
                                        found!          (PAUSE for confirmation)
                                              |
                                              +-------> merge into done event
                                                        status OVERRIDDEN to
                                                        "selecting_account"
                                                        (hold back summary,
                                                         show competitor picker first)

Request 8:         User confirms competitors
                   (shortcut - no graph!)
                   Now show real summary with
                   status: "awaiting_confirmation"
```

**The override hack**: When competitors are ready but not yet confirmed, the system lies about the status. It says `selecting_account` instead of `awaiting_confirmation` to prevent the frontend from showing the confirm button before competitors are picked.

---

## What the Frontend Should Actually Listen To

Given the duplicates and quirks, here's what matters:

```
MUST HANDLE:
  done          -->  THE source of truth. Update entire UI from this.
  content       -->  Stream into chat bubble (but ignore the final full-echo chunk)
  progress      -->  Show/hide loading spinners
  data          -->  field_update from "custom" source = real changes
                     website_summary = sidebar update
                     competitor_selection = show picker
                     analysis_complete = summary card

CAN SAFELY IGNORE:
  status        -->  Already in done.status (and has enum repr bug)
  field_update from "updates" mode  -->  Duplicates of custom mode
  Second progress start/end per node  -->  Wrapper duplicates
```

---

## Critique & Suggestions

### Problems Found

| # | Problem | Severity | What Happens |
|---|---------|----------|-------------|
| 1 | **Duplicate field_updates** from `updates` stream mode | High | Same field emitted 2-3x per node. Grows with fields. By request 6: 67% events are duplicates |
| 2 | **Full message echo** after token streaming | Medium | LLM response appears twice - once as tokens, once as blob |
| 3 | **Double progress start/end** per node | Low | Wrapper + node both emit start and end = 4 events instead of 2 |
| 4 | **Status string bug** | Medium | `updates` sends `"ChatStatus.IN_PROGRESS"`, `done` sends `"in_progress"`. Frontend must handle both |
| 5 | **Competitor status override** | Medium | `status` event says `AWAITING_CONFIRMATION`, `done` says `selecting_account`. Conflicting signals |
| 6 | **LLM batches fields unpredictably** | Medium | User says "google" in request 3, but `platform` doesn't appear in `collected_data` until request 5 |
| 7 | **Scrape replay on every request** | Low | `cache_check start/end` appears at top of every request after URL provided |

### Suggested Fixes

**Quick wins (< 1 hour each):**

1. **Fix status string bug** - In `_handle_state_update`, add:
   ```python
   status_val = status.value if hasattr(status, 'value') else str(status)
   ```

2. **Remove `_wrap_node` progress events** - Every node already emits better labeled start/end. The wrapper ones are generic noise.

3. **Filter the full-message echo** - In `_handle_message_chunk`, skip chunks where content length > 100 chars (the echo is always the full concatenated message).

**Medium effort (half day):**

4. **Remove `updates` from `stream_mode`** - The only thing it provides that `custom` doesn't is the `status` event. Add one `writer()` call in each node to emit status, then drop `updates` entirely. Eliminates ~80% of all duplicates.

5. **Add `SELECTING_COMPETITORS` status** - Make the competitor flow explicit in the state machine instead of hacking status overrides in `_build_response`.

**Larger improvements:**

6. **Force incremental field saves** - Adjust the system prompt to tell the LLM: "Call update_ad_plan after EVERY user message that provides info, even partial." This gives the frontend real-time field tracking.

7. **Only replay scrape on SSE reconnect** - Check for `Last-Event-ID` header before replaying. New messages don't need history.

### Bandwidth Impact of Duplicates

Rough estimate for a full session (8 requests):

```
Total events emitted:    ~250
Unique/useful events:    ~150
Duplicate events:        ~100  (40%)

Wasted bytes:            ~15-20 KB per session
```

Not a performance crisis, but it makes frontend logic harder (must deduplicate or ignore) and debugging confusing (logs full of repeated events).
