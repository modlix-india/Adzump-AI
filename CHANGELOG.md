# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] - 2026-02-02

### Added
- **Meta Campaign Agent** - LLM-based campaign payload generation
  - `POST /api/ds/ads/meta/campaign/generate` - Generate campaign from business website
  - `POST /api/ds/ads/meta/campaign/create` - Create campaign in Meta Ads
- **Clean Architecture** for Meta integration
  - `adapters/meta/` - Meta Graph API client with connection pooling
  - `agents/meta/` - Campaign agent with LLM orchestration
  - `core/` - Request-scoped auth context using contextvars
- **Auth Context Middleware** - Extracts headers into request-scoped context
- **Generic OAuth Token Fetching** - `fetch_oauth_token()` for any connection
- **MetaAPIError Exception Handler** - Returns actual Meta API status codes

### Changed
- Campaign names now include generation date suffix
- Meta API upgraded to Graph API v22.0
- `DatabaseException` now accepts optional `details` parameter

### Removed
- Legacy `services/meta/` directory
- Old `apis/meta_ads_api.py` router
- Unused `config/meta.py`
