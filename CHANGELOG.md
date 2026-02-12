# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] - 2026-02-02

### Added
- Meta campaign generation and creation via LLM-based agent
- Support for generic OAuth token fetching across integrations
- Budget prediction from conversions for Google Search campaigns

### Changed
- Campaign names now include generation date suffix
- Meta API upgraded to Graph API v22.0

### Improved
- Geo-targeting now discovers nearby localities within a configurable radius for more precise ad targeting
- Error responses now return actual API status codes for better debugging
- MLOps prediction modules reorganized with consistent code structure
- Exception handling improved with specific exception types and error logging
