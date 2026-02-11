# Meta Ads Campaign Agent

## Overview

This module provides intelligent Meta (Facebook) campaign creation using LLM-based generation.

## Architecture

```
agents/meta/
├── __init__.py
├── campaign_agent.py    # Main agent logic
└── README.md

adapters/meta/
├── __init__.py
├── client.py            # HTTP client for Meta Graph API
├── campaigns.py         # Campaign CRUD adapter
├── models.py            # Pydantic models
└── exceptions.py        # MetaAPIError

prompts/meta/
└── campaign.txt         # LLM prompt template
```

## Flow Diagram

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant Chat as Chat Service
    participant Session as Session Store
    participant Biz as Business Service
    participant Storage as Storage<br/>(AISuggestedData)
    participant Agent as Meta Campaign<br/>Agent
    participant LLM as OpenAI LLM
    participant Conn as Connection Service
    participant Meta as Meta Graph API

    rect rgb(240, 248, 255)
        Note over U,Session: Phase 1: Collect Business Data
        U->>Chat: Start chat session
        Chat->>Session: Create session
        Session-->>Chat: sessionId
        Chat-->>U: sessionId
        U->>Chat: Provide businessName, websiteURL
        Chat->>Session: Store campaign_data
    end

    rect rgb(255, 248, 240)
        Note over U,Storage: Phase 2: Process Website
        U->>Biz: POST /business/websiteSummary<br/>{websiteURL}
        Biz->>Biz: Scrape website
        Biz->>LLM: Generate summary
        LLM-->>Biz: Business summary
        Biz->>Storage: Store summary<br/>(key: businessUrl)
        Biz-->>U: Website processed
    end

    rect rgb(240, 255, 240)
        Note over U,LLM: Phase 3: Generate Campaign
        U->>Agent: POST /ads/meta/campaign/generate<br/>?sessionId=xxx
        Agent->>Session: Get campaign_data
        Session-->>Agent: websiteURL, businessName
        Agent->>Biz: process_website_data(websiteURL)
        Biz-->>Agent: Business summary
        Agent->>LLM: Generate campaign payload
        LLM-->>Agent: Campaign JSON
        Agent->>Agent: Append date to name
        Agent-->>U: CampaignPayload
    end

    rect rgb(255, 240, 245)
        Note over U,Meta: Phase 4: Create Campaign
        U->>Agent: POST /ads/meta/campaign/create<br/>{adAccountId, campaignPayload}
        Agent->>Conn: fetch_meta_api_token(clientCode)
        Conn-->>Agent: Meta access token
        Agent->>Meta: POST /v22.0/act_{id}/campaigns
        Meta-->>Agent: campaignId
        Agent-->>U: {campaignId}
    end
```

## API Endpoints

### Generate Campaign

```bash
POST /api/ds/ads/meta/campaign/generate?sessionId=xxx
```

**Headers:**
- `access-token`: Internal access token
- `clientCode`: Client code

**Response:**
```json
{
  "success": true,
  "data": {
    "name": "Business Name - Lead Gen Campaign - 2026-02-01",
    "objective": "OUTCOME_LEADS",
    "special_ad_categories": ["HOUSING"],
    "special_ad_category_country": ["IN"]
  }
}
```

### Create Campaign

```bash
POST /api/ds/ads/meta/campaign/create
```

**Headers:**
- `clientCode`: Client code (used to fetch Meta token from connection service)

**Body:**
```json
{
  "adAccountId": "123456789",
  "campaignPayload": {
    "name": "Campaign Name - 2026-02-01",
    "objective": "OUTCOME_LEADS",
    "special_ad_categories": ["NONE"],
    "special_ad_category_country": ["US"]
  }
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "campaignId": "120211234567890"
  }
}
```

## Valid Values

### Objectives
- `OUTCOME_LEADS`
- `OUTCOME_TRAFFIC`
- `OUTCOME_AWARENESS`

### Special Ad Categories
- `HOUSING`
- `EMPLOYMENT`
- `CREDIT`
- `ISSUES_ELECTIONS_POLITICS`
- `NONE`

## Token Management

Meta access tokens are fetched from the connection service using `fetch_meta_api_token(client_code)`. The token is retrieved per-request based on the `clientCode` header.

For local development, tokens can be configured in the connection service or via environment variables.
