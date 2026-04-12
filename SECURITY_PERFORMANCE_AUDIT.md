# Security, Reliability, and Performance Audit (Alpha → Beta Readiness)

Date: 2026-04-11  
Scope: `frontend/` + `backend/` architecture and code-path review, plus static test tooling attempts.

## What I Checked

- Backend auth/session handling, URL ingestion, processing pipeline, chat tooling, geocoding, retries, and trending paths.
- Frontend behavior for unavailable-content handling, polling/realtime behavior, and API integration points.
- Dependency-vulnerability scan attempts (`pip-audit`, `npm audit`) — both blocked by environment registry/proxy restrictions.

---

## Executive Summary (Senior Tester View)

Your core concept is strong and already has many good foundations (retry caps, unsupported-platform checks, unavailable-content detection, staged processing, and practical UX states).  
However, before public beta, you should prioritize **security hardening** and **processing architecture** changes to prevent account abuse, data leakage, and scale bottlenecks.

Most critical gaps:
1. Session cookies are not marked `Secure` (high risk in production).
2. Default admin credentials + auto-admin seeding pattern are dangerous if env config is weak.
3. Password-reset tokens are in-memory only and token is logged; reset is not production-safe.
4. No explicit rate limiting / abuse controls on auth and heavy endpoints.
5. Processing runs in FastAPI background tasks (single app instance scope), which is fragile at scale and during restarts.
6. Several API endpoints use N+1 query patterns that will slow down UX as data grows.

---

## Claim-by-Claim Verification (Your 9 backend assumptions)

## 1) "Checking the video is available or not"
**Status: PARTIALLY TRUE (implemented, but heuristic).**  
Implemented via `/api/check-url`, pre-save `quick_availability_check`, yt-dlp checks, and OG fallback. Good start; false positives/negatives still possible on platform anti-bot pages and transient failures.

## 2) "Number of retries limited"
**Status: TRUE.**  
`MAX_RETRIES = 3` with retry gate and stuck-item logic is present.

## 3) "404 animated + stale post self-destruct"
**Status: PARTIALLY TRUE.**  
Animated 404 tile exists and auto-expires in frontend pending-tile UX. But backend does **not** auto-delete stale unavailable rows globally (e.g., scheduled cleanup/TTL not present).

## 4) "AI assistant for library and each post"
**Status: TRUE.**  
Both `/api/chat/item/{id}` and `/api/chat/library` exist with streaming and optional web-search tool.

## 5) "Encrypted login passwords in Supabase"
**Status: LIKELY TRUE (via Supabase Auth), but app-level validation controls are weak.**  
Your app sends plain passwords to Supabase Auth endpoints (normal). Hashing is handled by Supabase, not your code. Add stronger password policy and anti-abuse controls.

## 6) "DB through Supabase Postgres"
**Status: TRUE.**

## 7) "FastAPI backend for parallelism"
**Status: PARTIALLY TRUE.**  
Async endpoints exist, but heavy processing is still mostly sequential per item and tied to web worker lifecycle.

## 8) "Frontend in React for future mobile"
**Status: TRUE (web React).**  
But current codebase is web React; direct Android/iOS deployment still needs React Native or wrapper strategy.

## 9) "Minimal UX"
**Status: TRUE-ish.**  
UI intent is clean/minimal. Main risk is latency/perceived slowness from processing pipeline and repeated polls.

---

## Top Security Vulnerabilities and Failure Points

## P0 (Fix before any public beta)

1. **Insecure auth cookies in production path**  
   - Access/refresh cookies are set with `secure=False`. This permits cookie transport over non-HTTPS paths and is unsafe for deployed environments.
   - Improve: set `secure=True` in prod, `SameSite=None` only if cross-site needed, and enforce HTTPS.

2. **Weak default admin bootstrap pattern**  
   - Defaults include `admin@example.com` / `admin123`, plus startup admin creation/reset behavior.
   - Improve: require env vars at boot, fail fast if defaults detected in non-dev mode, one-time bootstrap script instead of runtime auto-seeding.

3. **Password reset token handling is non-production-safe**
   - Tokens are held in-memory and logged directly; restart loses tokens, logs leak secrets.
   - Improve: store hashed reset tokens in DB with TTL, single-use flag, rate limits, and never log raw tokens.

4. **No explicit rate limiting / brute-force controls**
   - Auth and heavy endpoints can be abused (`register/login/forgot/save/chat/retry`).
   - Improve: per-IP + per-user limits, exponential backoff, CAPTCHA on suspicious patterns, and WAF rules.

## P1 (Fix during private beta hardening)

5. **Service-role usage from app server across user lifecycle operations**
   - App calls admin APIs directly (create users / update users). This is powerful and increases blast radius if backend is compromised.
   - Improve: minimize direct admin operations, isolate admin routes, rotate keys, monitor key usage, and restrict infra egress.

6. **Potential data exposure risk from permissive realtime-policy guidance**
   - Inline SQL comment suggests `anon SELECT` policy on items for realtime setup. That can leak metadata if applied broadly.
   - Improve: enforce RLS strictly by `auth.uid() = user_id`; never enable global anon read for user content.

7. **Prompt/tool abuse surface in chat**
   - Chat can call web-search tool; no explicit content safety rules, no tool-call budget controls, and no hostile prompt suppression.
   - Improve: add moderation/guardrails, max tool calls per request, domain filters for sensitive responses, and strict system prompt hardening.

## P2 (important quality/security robustness)

8. **User-generated text rendered in multiple views**
   - Ensure all rendered markdown/HTML paths are sanitized (React defaults are safer unless dangerouslySetInnerHTML is used).
   - Improve: keep plain-text rendering or sanitize HTML aggressively.

9. **Error transparency can leak internals**
   - Some endpoints return raw exception strings in `detail`.
   - Improve: map internal errors to user-safe messages and log detailed stack traces server-side only.

---

## Parallel Processing + Performance Bottlenecks (Why it feels slow)

1. **Single-request chained processing pipeline per item**
   - Current pipeline is sequential: metadata → vision → transcript → AI categorization → embedding → geocoding.
   - Improvement:
     - Run vision and transcript concurrently (`asyncio.gather`) once metadata is available.
     - Defer non-critical work (embedding/geocoding) after first usable summary response.

2. **FastAPI `BackgroundTasks` is not a durable queue**
   - Jobs die on process restart; scaling to multiple instances risks duplicated/missed work.
   - Improvement: move to queue workers (Celery/RQ/Arq + Redis, or managed queue). Keep job state transitions idempotent.

3. **N+1 query patterns (major latency source)**
   - `get_item`, `list_collections`, `get_collection`, and `map` endpoints loop and call DB repeatedly.
   - Improvement: replace loops with joins/RPC/batched `in_` queries; return shaped responses directly from SQL/RPC.

4. **Polling every 3s can create unnecessary load**
   - Home page uses aggressive polling while processing.
   - Improvement: prefer realtime events/webhooks; fallback poll with backoff (3s → 5s → 10s).

5. **External API tail latency (yt-dlp + Whisper + LLM)**
   - Instagram/Facebook extraction is brittle and slower under anti-bot controls.
   - Improvement:
     - Cache extraction results per canonicalized URL for a short TTL.
     - Add per-step timeout budget + circuit breaker + reason-coded failures.
     - Add provider fallback for non-YouTube sources.

6. **Search endpoint post-filters tags in app layer**
   - Tag filtering after page retrieval can produce inconsistent pagination.
   - Improvement: move tag filter into SQL/RPC.

---

## Integration-Point Review (Where failures will happen first)

- **yt-dlp integration:** best on YouTube, flaky on some reels/private/region-gated media; enforce deterministic error codes and fallback providers.
- **OpenAI integration:** high latency variance; protect with queue, retries with jitter, and per-user quotas.
- **Supabase integration:** strong base; ensure RLS consistency and avoid using service-role for regular user paths where possible.
- **HERE maps + geocoding accuracy:** quality depends on extracted place text fidelity; add user correction workflow telemetry and confidence thresholds.
- **Brave search in chat:** useful for fact-checking, but adds latency and tool-call unpredictability.

---

## Deployment Recommendation (No-cost alpha/beta)

Best zero-cost stack for your current architecture:

1. **Frontend:** Vercel (already aligned with React build + good DX).
2. **Backend:** Render free web service *or* Fly.io free allowance (if available in your region/account; free tiers change).
3. **Database/Auth:** Supabase free tier (already used).
4. **Queue (if added):** Upstash Redis free tier for lightweight queue/cache.

If you want pure no-cost and fastest launch:
- **Option A (quickest):** Vercel frontend + Render backend + Supabase.
- **Option B (lower cold-start pain):** Fly.io backend + Vercel frontend + Supabase.

Note: free tiers can throttle/sleep; for beta UX testing this is acceptable if you set user expectations.

---

## What to Prove Before Moving Alpha → Beta (Test Checklist)

## Security hardening checklist
- [ ] Cookies secure in production + HTTPS only.
- [ ] No default admin credentials accepted in prod.
- [ ] Password reset flow moved to DB-backed hashed tokens with TTL.
- [ ] Rate limiting enabled for auth/save/chat/retry endpoints.
- [ ] RLS validation test suite (cross-user access denied for every table/API).
- [ ] Remove sensitive token/password logging.

## Reliability checklist
- [ ] Durable async job queue in place; restart-safe processing.
- [ ] Idempotent job design (same URL/process retrigger should not corrupt data).
- [ ] Dead-letter handling for permanently failing links.
- [ ] Job-level observability (step timing, failure reason taxonomy).

## Performance checklist
- [ ] P95 and P99 latency baseline per API endpoint.
- [ ] Pipeline split into “fast first result” vs “full enrichment” phases.
- [ ] N+1 queries removed from high-traffic endpoints.
- [ ] Client polling replaced with realtime/backoff strategy.
- [ ] Cache hit-rate tracking for repeated URLs and metadata calls.

## Product-quality checklist
- [ ] Mapping accuracy benchmark (precision/recall on curated place dataset).
- [ ] Bullet-point extraction quality eval set by content type (recipe/travel/shopping/tutorial).
- [ ] Human override workflow for wrong categorization and places.
- [ ] Reels/shorts source compatibility matrix and known failure reasons.

---

## Concrete Improvement Plan (90-day practical sequence)

### Phase A (Week 1–2): Security blockers
- Cookie security + env safeguards + logging cleanup.
- Rate limiting + brute-force protection.
- Reset-token redesign.

### Phase B (Week 3–5): Architecture & speed
- Move processing from BackgroundTasks to queue workers.
- Parallelize transcript+vision and defer low-priority enrichment.
- Add caching + retry/circuit-breaker wrappers for external calls.

### Phase C (Week 6–8): Data and query optimization
- Replace N+1 endpoints with join/RPC patterns.
- Add telemetry dashboards (error codes, step durations, retries).

### Phase D (Week 9–12): Beta readiness
- Add automated security/regression tests.
- Run closed beta load test with synthetic + real user traffic.
- Tighten UX around queued states and long-running jobs.

---

## Tooling/Validation Commands I Ran

- `python -m pip --version`
- `python -m pip install --quiet pip-audit && pip-audit -r backend/requirements.txt` (failed due to registry/proxy restrictions in this environment)
- `cd frontend && npm audit --omit=dev --json` (failed due to `403 Forbidden` from npm advisory endpoint in this environment)

