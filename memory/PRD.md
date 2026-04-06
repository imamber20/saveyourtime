# Content Memory App - PRD

## Overview
Web-first content organizer for saving and AI-organizing Instagram Reels, YouTube Shorts, and Facebook Reels. "Save once, organize automatically, find instantly."

## Architecture
- **Backend**: FastAPI (Python) on port 8001
- **Frontend**: React.js with Tailwind CSS on port 3000
- **Database**: MongoDB (local)
- **AI**: OpenAI GPT-4o-mini via Emergent LLM key for categorization/summarization
- **Maps**: Leaflet + OpenStreetMap (Nominatim for geocoding)
- **Auth**: JWT (httpOnly cookies) with email/password
- **Extraction**: yt-dlp (YouTube), BeautifulSoup (OpenGraph metadata)

## User Personas
1. Content consumers who save useful reels/shorts
2. Travelers collecting places to visit
3. Learners saving educational tips
4. Fitness users saving workouts
5. Food/recipe collectors

## Core Requirements (Static)
- Save URL in one step
- Auto-extract metadata from source
- AI-based categorization, summarization, tagging
- Custom categories and user edits
- Fast search (keyword + filters)
- Collections / boards
- Map view for place-related content
- No permanent media storage

## What's Been Implemented (2026-04-06)
### V1 - Full MVP
- [x] JWT auth (register, login, logout, refresh, password reset)
- [x] Admin seeding with brute force protection
- [x] Save flow: URL validation, platform detection (Instagram/YouTube/Facebook)
- [x] Async background processing pipeline
- [x] Metadata extraction (yt-dlp for YouTube, OpenGraph for others)
- [x] AI categorization with GPT-4o-mini (structured JSON output with validation)
- [x] 25 predefined categories with custom category support
- [x] Place detection and geocoding via Nominatim
- [x] MongoDB text search with filters (category, platform, tags, collection)
- [x] Collections CRUD (create, add/remove items, delete)
- [x] Map view with Leaflet markers for place-related items
- [x] Item detail view with edit capability
- [x] Retry failed processing
- [x] Pagination
- [x] Beautiful warm organic UI theme (Outfit + Manrope fonts)
- [x] Responsive design (mobile-friendly)
- [x] Empty states with bonsai illustration
- [x] Full test coverage (100% backend, 100% frontend)

### API Endpoints
- POST /api/auth/register, login, logout, refresh, forgot-password, reset-password
- GET /api/auth/me
- POST /api/save
- GET/PUT/DELETE /api/items/{id}
- GET /api/items (paginated, filtered)
- POST /api/items/{id}/retry
- POST/GET /api/collections
- GET/PUT/DELETE /api/collections/{id}
- POST /api/collections/{id}/items
- DELETE /api/collections/{id}/items/{id}
- GET /api/search
- GET /api/map
- GET /api/categories
- GET /api/health

## Prioritized Backlog

### P0 (Critical)
- All P0 items implemented

### P1 (Important)
- [ ] Semantic search with text-embedding-3-small
- [ ] Temporary video processing (audio transcription via Whisper)
- [ ] Frame extraction + OCR for on-screen text
- [ ] User registration flow improvements (email validation)

### P2 (Nice to Have)
- [ ] Batch URL import
- [ ] Export collections
- [ ] Rename collections inline
- [ ] Dark mode toggle
- [ ] Keyboard shortcuts
- [ ] Drag-and-drop collection management
- [ ] Sharing collections (public links)

## Next Tasks
1. Add semantic search with OpenAI embeddings
2. Implement audio transcription pipeline
3. Add frame OCR for richer metadata
4. Implement collection sharing
5. Add batch URL import feature
