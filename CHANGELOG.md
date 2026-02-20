# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.0] - 2026-02-16

### Breaking Changes
- Rename `login_id` parameter to `login_customer_id` in Google Ads mutation API (#220)

### Added
- Add keyword optimization agent with LLM analysis and Google Keyword Planner integration (#206)
- Add search term optimization agent with recommendation storage and performance analysis (#203)
- Add age demographics optimization agent with LLM-driven recommendations (#204)
- Add location optimization agent with rule-based performance evaluation (#207)
- Add criterion `resource_name` support for location optimization recommendations (#217)
- Add Google Ads mutation service with centralized operation builders for targeting (#220)
- Add `resource_name` and criterion status to age/gender optimization recommendations (#224)
- Add structured logging with request tracing and retry logic for ad asset generation (#213)
- Add local OAuth token auto-refresh for development environments (#207)

### Changed
- Read auth token from `Authorization` header instead of `access-token` header (#206)

### Fixed
- Fix search term storage persistence for age optimization agent (#209)
- Skip search terms exceeding 80-character Google keyword limit (#228)
- Hardcode SEARCH campaign type in age and search term agents (#226)
- Preserve uppercase keyword match types and normalize search term match types (#222)

## [1.0.0] - 2026-02-02

### Added
- Meta campaign generation and creation via LLM-based agent
- Support for generic OAuth token fetching across integrations
- Budget prediction from conversions for Google Search campaigns

### Changed
- Campaign names now include generation date suffix
- Meta API upgraded to Graph API v22.0
- Geo-targeting now discovers nearby localities within a configurable radius for more precise ad targeting
- Error responses now return actual API status codes for better debugging
- MLOps prediction modules reorganized with consistent code structure
- Exception handling improved with specific exception types and error logging

### Fixed
- Remove incorrect `__init__` method from `ModelNotLoadedException` (#196)
