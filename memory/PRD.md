# Content Memory App - PRD

## Overview
Web-first content organizer for saving and AI-organizing Instagram Reels, YouTube Shorts, and Facebook Reels. "Save once, organize automatically, find instantly."

## Architecture
- **Backend**: FastAPI (Python) on port 8001
- **Frontend**: React.js with Tailwind CSS on port 3000
- **Database**: MongoDB (local)
- **AI**: OpenAI GPT-4o-mini (direct API key) for categorization/summarization
- **Embeddings**: OpenAI text-embedding-3-small (ready)
- **Transcription**: OpenAI Whisper (implemented)
- **Maps**: Leaflet + OpenStreetMap (Nominatim for geocoding)
- **Auth**: JWT (httpOnly cookies) with email/password
- **Extraction**: yt-dlp (YouTube), BeautifulSoup (OpenGraph metadata)

## What's Been Implemented (2026-04-06)
### V1 - Full MVP
- [x] JWT auth (register, login, logout, refresh, password reset, brute force protection)
- [x] Admin seeding with demo credentials visible on login page
- [x] Save flow: URL validation, platform detection (Instagram/YouTube/Facebook)
- [x] Async background processing pipeline
- [x] Metadata extraction (yt-dlp for YouTube, OpenGraph for others)
- [x] AI categorization with GPT-4o-mini (structured JSON output with validation)
- [x] OpenAI Whisper transcription pipeline (for YouTube audio)
- [x] 25 predefined categories with custom category support
- [x] Place detection and geocoding via Nominatim
- [x] MongoDB text search with filters
- [x] Collections CRUD
- [x] Map view with Leaflet markers
- [x] Item detail with edit, delete, retry, add-to-collection
- [x] Pagination, polling for processing items
- [x] Warm organic UI theme (Outfit + Manrope fonts)

### Iteration 2 (2026-04-06)
- [x] Switched from Emergent LLM key to user's direct OpenAI API key
- [x] Added Whisper transcription pipeline
- [x] Added embedding generation capability (text-embedding-3-small)
- [x] Fixed yt-dlp path resolution
- [x] Added "Fill" demo credentials button on login page

## Prioritized Backlog
### P1
- [ ] Semantic search with embeddings
- [ ] Frame OCR for on-screen text
- [ ] Batch URL import

### P2
- [ ] Dark mode, keyboard shortcuts
- [ ] Collection sharing, export
- [ ] Browser extension
