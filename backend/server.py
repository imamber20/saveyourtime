from dotenv import load_dotenv
load_dotenv()

import os
import re
import asyncio
import logging
import secrets
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from contextlib import asynccontextmanager

import jwt as pyjwt
import httpx
from fastapi import FastAPI, HTTPException, Request, Response, Depends, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from supabase import acreate_client, AsyncClient

from services.extraction import (
    validate_url, detect_platform, extract_metadata,
    ContentUnavailableError, quick_availability_check,
)
from services.ai_service import categorize_content
from services.geocoding import geocode_place

MAX_RETRIES = 3

# ─── Supabase helper ─────────────────────────────────────────────────────────
def _first(res) -> Optional[dict]:
    """Return the first row from a supabase query result as a plain dict, or None.
    Handles the supabase-py v2 bug where maybe_single().execute() returns None
    instead of a response object when no rows are found.
    Use with .limit(1).execute() — never .limit(1).execute()."""
    if res is None:
        return None
    data = res.data if hasattr(res, "data") else res
    if not data:
        return None
    return data[0] if isinstance(data, list) else data

# ─── Config ───────────────────────────────────────────────────────────────────
SUPABASE_URL             = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
JWT_SECRET               = os.environ["JWT_SECRET"]   # signs our own session tokens
JWT_ALGORITHM            = "HS256"
ADMIN_EMAIL              = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower().strip()
ADMIN_PASSWORD           = os.environ.get("ADMIN_PASSWORD", "admin123")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("content_memory")

# ─── Supabase async client (initialised in lifespan) ─────────────────────────
supabase: AsyncClient = None   # type: ignore[assignment]


# ─── JWT helpers ─────────────────────────────────────────────────────────────
def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id, "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=60),
        "type": "access",
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh",
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def set_auth_cookies(response: Response, access_token: str, refresh_token: str):
    response.set_cookie("access_token",  access_token,  httponly=True, secure=False, samesite="lax", max_age=3600,   path="/")
    response.set_cookie("refresh_token", refresh_token, httponly=True, secure=False, samesite="lax", max_age=604800, path="/")


# ─── Auth dependency ──────────────────────────────────────────────────────────
async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        return {"id": payload["sub"], "email": payload["email"]}
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ─── Pydantic schemas ─────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = "User"

class LoginRequest(BaseModel):
    email: str
    password: str

class SaveRequest(BaseModel):
    url: str

class UpdateItemRequest(BaseModel):
    title:        Optional[str]       = None
    summary:      Optional[str]       = None
    category:     Optional[str]       = None
    sub_category: Optional[str]       = None
    tags:         Optional[List[str]] = None
    notes:        Optional[str]       = None
    key_points:   Optional[List[str]] = None
    steps:        Optional[List[str]] = None
    ingredients:  Optional[List[str]] = None

class CreateCollectionRequest(BaseModel):
    name: str
    description: Optional[str] = ""

class AddItemToCollectionRequest(BaseModel):
    item_id: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

# In-memory password-reset tokens (no DB needed for this local app)
_reset_tokens: dict = {}


# ─── Lifespan ─────────────────────────────────────────────────────────────────
DEFAULT_COLLECTIONS = [
    {"name": "Fitness & Health",  "description": "Workouts, wellness tips, and health routines"},
    {"name": "Travel",            "description": "Places to visit, travel tips, and destination guides"},
    {"name": "Food & Recipes",    "description": "Recipes, cooking techniques, and restaurant finds"},
    {"name": "Technology",        "description": "Tech tutorials, gadget reviews, and digital tips"},
    {"name": "Learning",          "description": "Educational content, how-tos, and skill-building"},
    {"name": "Entertainment",     "description": "Fun videos, comedy, music, and pop culture"},
    {"name": "Finance",           "description": "Money tips, investing advice, and personal finance"},
    {"name": "Fashion & Style",   "description": "Outfits, beauty tips, skincare, and shopping picks"},
]

async def seed_default_collections(user_id: str):
    """Create default collections for a new user if they don't already exist."""
    now = datetime.now(timezone.utc).isoformat()
    for coll in DEFAULT_COLLECTIONS:
        existing = await supabase.table("collections").select("id") \
            .eq("user_id", user_id).eq("name", coll["name"]) \
            .limit(1).execute()
        if not existing.data:
            await supabase.table("collections").insert({
                "user_id": user_id,
                "name": coll["name"],
                "description": coll["description"],
                "created_at": now,
                "updated_at": now,
            }).execute()


_HYPE_MIGRATION_SQL = """
-- Phase 5: Hype & Trending (auto-applied at startup)
CREATE TABLE IF NOT EXISTS public.hypes (
  item_id    uuid NOT NULL REFERENCES public.items(id) ON DELETE CASCADE,
  user_id    uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (item_id, user_id)
);
ALTER TABLE public.hypes ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='hypes' AND policyname='users_manage_own_hypes') THEN
    CREATE POLICY "users_manage_own_hypes" ON public.hypes
      FOR ALL TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='hypes' AND policyname='anon_read_hypes') THEN
    CREATE POLICY "anon_read_hypes" ON public.hypes FOR SELECT TO anon USING (true);
  END IF;
END $$;

ALTER TABLE public.items ADD COLUMN IF NOT EXISTS hype_count INT NOT NULL DEFAULT 0;
ALTER TABLE public.items ADD COLUMN IF NOT EXISTS is_public  BOOLEAN NOT NULL DEFAULT false;

CREATE OR REPLACE FUNCTION public.update_hype_count()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    UPDATE public.items SET hype_count = hype_count + 1, is_public = true WHERE id = NEW.item_id;
  ELSIF TG_OP = 'DELETE' THEN
    UPDATE public.items SET hype_count = GREATEST(hype_count - 1, 0) WHERE id = OLD.item_id;
  END IF;
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS hype_counter ON public.hypes;
CREATE TRIGGER hype_counter
  AFTER INSERT OR DELETE ON public.hypes
  FOR EACH ROW EXECUTE FUNCTION public.update_hype_count();

CREATE INDEX IF NOT EXISTS items_hype_count_idx
  ON public.items (hype_count DESC) WHERE is_public = true;
"""

async def _apply_startup_migrations():
    """
    Best-effort: apply the hype tables DDL at startup.
    Tries the Supabase Management API if SUPABASE_MANAGEMENT_TOKEN is set.
    Falls back to a clear log message with manual instructions.
    """
    mgmt_token = os.environ.get("SUPABASE_MANAGEMENT_TOKEN", "")
    project_ref = SUPABASE_URL.rstrip("/").split("//")[-1].split(".")[0]

    if mgmt_token:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"https://api.supabase.io/v1/projects/{project_ref}/database/query",
                    headers={
                        "Authorization": f"Bearer {mgmt_token}",
                        "Content-Type":  "application/json",
                    },
                    json={"query": _HYPE_MIGRATION_SQL},
                )
                if resp.status_code in (200, 201):
                    logger.info("✅  Hype tables migration applied via Management API")
                    return
                else:
                    logger.warning(f"Management API migration failed: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"Management API migration error: {e}")

    # Silent probe: check if hypes table already exists
    try:
        await supabase.table("hypes").select("item_id").limit(1).execute()
        logger.info("Hype tables already present — skipping migration.")
        return
    except Exception:
        pass  # table doesn't exist

    logger.warning(
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️  PENDING MIGRATION: Hype & Trending tables are NOT set up yet.\n"
        "   Trending page will show empty until you apply the migration.\n\n"
        "   1. Open: https://supabase.com/dashboard/project/"
        f"{project_ref}/sql/new\n"
        "   2. Paste & run: backend/scripts/create_hype_tables.sql\n\n"
        "   — OR — add SUPABASE_MANAGEMENT_TOKEN to backend/.env for\n"
        "   automatic migration next time the server starts.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global supabase
    supabase = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    logger.info("Supabase client initialised")

    # Seed / verify admin user
    admin_id = None
    try:
        # Happy path: admin exists with the correct password
        res      = await supabase.auth.sign_in_with_password(
            {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        admin_id = res.user.id
        logger.info(f"Admin login OK: {ADMIN_EMAIL}")
    except Exception:
        # Either doesn't exist OR password is stale (e.g. after migration with temp pw)
        try:
            all_users      = await supabase.auth.admin.list_users()
            existing_admin = next((u for u in all_users if u.email == ADMIN_EMAIL), None)

            if existing_admin:
                # Exists but wrong password — reset it via direct httpx
                admin_id = existing_admin.id
                async with httpx.AsyncClient(timeout=15) as _hc:
                    await _hc.put(
                        f"{SUPABASE_URL}/auth/v1/admin/users/{admin_id}",
                        headers={
                            "apikey":        SUPABASE_SERVICE_ROLE_KEY,
                            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                            "Content-Type":  "application/json",
                        },
                        json={"password": ADMIN_PASSWORD},
                    )
                logger.info(f"Admin password reset to configured value: {ADMIN_EMAIL}")
            else:
                # Truly new — create via direct httpx (supabase-py omits apikey header)
                async with httpx.AsyncClient(timeout=15) as _hc:
                    _r = await _hc.post(
                        f"{SUPABASE_URL}/auth/v1/admin/users",
                        headers={
                            "apikey":        SUPABASE_SERVICE_ROLE_KEY,
                            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                            "Content-Type":  "application/json",
                        },
                        json={
                            "email":         ADMIN_EMAIL,
                            "password":      ADMIN_PASSWORD,
                            "email_confirm": True,
                            "user_metadata": {"name": "Admin", "role": "admin"},
                        },
                    )
                _r.raise_for_status()
                admin_id = _r.json().get("id")
                logger.info(f"Admin user created: {ADMIN_EMAIL}")

            # Ensure profile has role=admin
            await supabase.table("profiles").update({"role": "admin", "name": "Admin"}) \
                .eq("id", admin_id).execute()
            await seed_default_collections(admin_id)
        except Exception as err:
            logger.warning(f"Admin seeding skipped: {err}")

    # Write test credentials to memory dir
    memory_dir = os.environ.get(
        "MEMORY_DIR", os.path.join(os.path.dirname(__file__), "..", "memory")
    )
    os.makedirs(memory_dir, exist_ok=True)
    with open(os.path.join(memory_dir, "test_credentials.md"), "w") as f:
        f.write("# Test Credentials\n\n")
        f.write(f"## Admin\n- Email: {ADMIN_EMAIL}\n- Password: {ADMIN_PASSWORD}\n- Role: admin\n\n")
        f.write("## Auth Endpoints\n")
        f.write("- POST /api/auth/register\n- POST /api/auth/login\n"
                "- POST /api/auth/logout\n- GET /api/auth/me\n- POST /api/auth/refresh\n")

    # Apply pending DDL migrations (best-effort; never crashes the server)
    try:
        await _apply_startup_migrations()
    except Exception as _mig_err:
        logger.warning(f"Startup migration attempt failed: {_mig_err}")

    logger.info("Content Memory API started (Supabase backend)")
    yield
    # supabase-py HTTP client cleans up automatically


# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Content Memory API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_URL", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health ───────────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "content-memory",
            "timestamp": datetime.now(timezone.utc).isoformat()}


# ─── Auth Routes ──────────────────────────────────────────────────────────────
@app.post("/api/auth/register")
async def register(req: RegisterRequest, response: Response,
                   background_tasks: BackgroundTasks):
    email = req.email.lower().strip()
    user_id: str = ""

    # ── Attempt 1a: Direct httpx call to GoTrue admin endpoint ───────────────
    # supabase-py sometimes omits the 'apikey' header that GoTrue admin requires;
    # using httpx directly ensures both required headers are present.
    try:
        project_ref = SUPABASE_URL.rstrip("/").split("//")[-1].split(".")[0]
        async with httpx.AsyncClient(timeout=15) as _hc:
            _r = await _hc.post(
                f"{SUPABASE_URL}/auth/v1/admin/users",
                headers={
                    "apikey":        SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type":  "application/json",
                },
                json={
                    "email":          email,
                    "password":       req.password,
                    "email_confirm":  True,
                    "user_metadata":  {"name": req.name},
                },
            )
        if _r.status_code in (200, 201):
            _data   = _r.json()
            user_id = _data.get("id", "")
            if not user_id:
                raise Exception("No user id in response")
            logger.info(f"User created via direct GoTrue admin: {email}")
        else:
            raise Exception(f"GoTrue {_r.status_code}: {_r.text[:200]}")
    except Exception as admin_err:
        admin_msg = str(admin_err).lower()
        if any(x in admin_msg for x in ("already registered", "already exists",
                                         "unique", "duplicate", "user already")):
            raise HTTPException(status_code=400, detail="Email already registered")

        # ── Attempt 2: Standard sign_up (works even when admin API is restricted) ─
        logger.warning(f"Admin create_user failed ({admin_err}); falling back to sign_up")
        try:
            res2 = await supabase.auth.sign_up({
                "email": email,
                "password": req.password,
                "options": {"data": {"name": req.name}},
            })
            if not res2.user:
                raise HTTPException(status_code=400,
                                    detail="Registration failed: no user returned")
            user_id = res2.user.id
            # Immediately confirm the email so the user can log in right away
            try:
                await supabase.auth.admin.update_user_by_id(
                    user_id, {"email_confirm": True}
                )
            except Exception:
                pass  # Email confirmation update failed — user may need to verify email
        except HTTPException:
            raise
        except Exception as e2:
            msg2 = str(e2).lower()
            if any(x in msg2 for x in ("already registered", "already exists",
                                        "unique", "duplicate", "user already")):
                raise HTTPException(status_code=400, detail="Email already registered")

            # ── Attempt 3: sign_up may have created the user but hit the email
            #    rate limit before sending the confirmation.  The user row exists
            #    in auth.users — look it up and confirm via admin API so they can
            #    log in immediately without needing to click a verification link.
            if any(x in msg2 for x in ("rate limit", "email rate", "too many")):
                logger.warning(f"sign_up rate-limited for {email}; trying admin lookup+confirm via httpx")
                try:
                    async with httpx.AsyncClient(timeout=15) as _hc:
                        _list = await _hc.get(
                            f"{SUPABASE_URL}/auth/v1/admin/users",
                            headers={
                                "apikey":        SUPABASE_SERVICE_ROLE_KEY,
                                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                            },
                            params={"per_page": 1000},
                        )
                    _users = _list.json() if _list.status_code == 200 else {}
                    _all   = _users.get("users", []) if isinstance(_users, dict) else []
                    _found = next((u for u in _all if u.get("email") == email), None)
                    if _found:
                        user_id = _found["id"]
                        # Confirm the user so they can log in without clicking a link
                        async with httpx.AsyncClient(timeout=15) as _hc:
                            await _hc.put(
                                f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
                                headers={
                                    "apikey":        SUPABASE_SERVICE_ROLE_KEY,
                                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                                    "Content-Type":  "application/json",
                                },
                                json={"email_confirm": True},
                            )
                        logger.info(f"Confirmed rate-limited sign_up user {email} via admin PUT")
                    else:
                        raise HTTPException(
                            status_code=429,
                            detail="Too many sign-up attempts. Please wait a few minutes and try again."
                        )
                except HTTPException:
                    raise
                except Exception as e3:
                    raise HTTPException(status_code=400, detail=f"Registration failed: {e2}")
            else:
                raise HTTPException(status_code=400, detail=f"Registration failed: {e2}")

    access_token  = create_access_token(user_id, email)
    refresh_token = create_refresh_token(user_id)
    set_auth_cookies(response, access_token, refresh_token)
    background_tasks.add_task(seed_default_collections, user_id)
    return {"id": user_id, "email": email, "name": req.name, "role": "user"}


@app.post("/api/auth/login")
async def login(req: LoginRequest, response: Response):
    email = req.email.lower().strip()
    try:
        res  = await supabase.auth.sign_in_with_password(
            {"email": email, "password": req.password}
        )
        user = res.user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user_id = user.id
    meta    = user.user_metadata or {}
    name    = meta.get("name", "")

    # Fetch role from profiles table
    prof = await supabase.table("profiles").select("role, name") \
        .eq("id", user_id).limit(1).execute()
    role = (_first(prof) or {}).get("role", "user")
    if not name:
        name = (_first(prof) or {}).get("name", "")

    access_token  = create_access_token(user_id, email)
    refresh_token = create_refresh_token(user_id)
    set_auth_cookies(response, access_token, refresh_token)
    return {"id": user_id, "email": email, "name": name, "role": role}


@app.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token",  path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"message": "Logged out"}


@app.get("/api/auth/me")
async def me(user: dict = Depends(get_current_user)):
    prof = await supabase.table("profiles").select("name, role") \
        .eq("id", user["id"]).limit(1).execute()
    _p = _first(prof)
    if _p:
        user["name"] = _p.get("name", "")
        user["role"] = _p.get("role", "user")
    return user


@app.post("/api/auth/refresh")
async def refresh_token_endpoint(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = payload["sub"]
        # Verify user still exists
        try:
            res   = await supabase.auth.admin.get_user_by_id(user_id)
            email = res.user.email
        except Exception:
            raise HTTPException(status_code=401, detail="User not found")
        new_access = create_access_token(user_id, email)
        response.set_cookie("access_token", new_access, httponly=True,
                            secure=False, samesite="lax", max_age=3600, path="/")
        return {"message": "Token refreshed"}
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


@app.post("/api/auth/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    email = req.email.lower().strip()
    # Look up user
    user_id = None
    try:
        page = await supabase.auth.admin.list_users()
        for u in page:
            if u.email == email:
                user_id = u.id
                break
    except Exception:
        pass

    if not user_id:
        return {"message": "If the email exists, a reset link has been sent."}

    token = secrets.token_urlsafe(32)
    _reset_tokens[token] = {
        "user_id": user_id,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    logger.info(f"Password reset token for {email}: {token}")
    return {"message": "If the email exists, a reset link has been sent."}


@app.post("/api/auth/reset-password")
async def reset_password(req: ResetPasswordRequest):
    record = _reset_tokens.get(req.token)
    if not record or record["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    try:
        await supabase.auth.admin.update_user_by_id(
            record["user_id"], {"password": req.new_password}
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Password reset failed: {e}")
    _reset_tokens.pop(req.token, None)
    return {"message": "Password reset successfully"}


# ─── URL Availability Check ──────────────────────────────────────────────────
@app.get("/api/check-url")
async def check_url_endpoint(url: str, user: dict = Depends(get_current_user)):
    if not validate_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL")
    return await quick_availability_check(url)


# ─── Save Flow ────────────────────────────────────────────────────────────────
@app.post("/api/save")
async def save_url(req: SaveRequest, background_tasks: BackgroundTasks,
                   user: dict = Depends(get_current_user)):
    url = req.url.strip()
    if not validate_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL")

    platform = detect_platform(url)
    if not platform:
        raise HTTPException(
            status_code=400,
            detail="Unsupported platform. Only Instagram Reels, YouTube Shorts, and Facebook Reels are supported.",
        )

    # Pre-save availability check — confirms the post still exists so we can
    # morph the checking tile into the animated 404 "content gone" card and
    # auto-expire it instead of writing a dead row to the library.
    check = await quick_availability_check(url)
    if not check.get("available", True):
        raise HTTPException(
            status_code=404,
            detail={
                "type": "unavailable",
                "reason": check.get("reason", "Content no longer available"),
            },
        )

    # Duplicate check
    dup = await supabase.table("items").select("id") \
        .eq("url", url).eq("user_id", user["id"]).limit(1).execute()
    _dup = _first(dup)
    if _dup:
        return {"item_id": _dup["id"], "status": "duplicate",
                "message": "This URL has already been saved."}

    now = datetime.now(timezone.utc).isoformat()
    item_doc = {
        "user_id":          user["id"],
        "url":              url,
        "platform":         platform,
        "title":            "",
        "summary":          "",
        "author":           "",
        "duration":         "",
        "key_points":       [],
        "steps":            [],
        "ingredients":      [],
        "transcript_excerpt": "",
        "visual_text":      "",
        "category":         "",
        "sub_category":     "",
        "tags":             [],
        "thumbnail_url":    "",
        "source_status":    "processing",
        "is_place_related": False,
        "is_public":        False,
        "confidence_score": 0.0,
        "notes":            "",
        "retry_count":      0,
        "hype_count":       0,
        "created_at":       now,
        "updated_at":       now,
    }
    result  = await supabase.table("items").insert(item_doc).execute()
    item_id = result.data[0]["id"]

    await supabase.table("processing_jobs").insert({
        "item_id":      item_id,
        "status":       "pending",
        "step_name":    "metadata_extraction",
        "error_message": "",
        "started_at":   now,
        "completed_at": None,
    }).execute()

    background_tasks.add_task(process_item, item_id, url, platform, user["id"])
    return {"item_id": item_id, "status": "processing"}


# ─── Category → Collection Auto-Assignment ───────────────────────────────────
CATEGORY_COLLECTION_MAP = {
    # Fitness
    "Fitness & Health":       "Fitness & Health",
    "Sports":                 "Fitness & Health",
    # Travel
    "Travel":                 "Travel",
    "Nature & Outdoors":      "Travel",
    "Home & Interior":        "Travel",   # catch-all for lifestyle
    # Food
    "Food & Recipes":         "Food & Recipes",
    # Tech
    "Technology":             "Technology",
    # Learning
    "Education & Learning":   "Learning",
    "DIY & Crafts":           "Learning",
    "Parenting":              "Learning",
    "Motivation":             "Learning",
    "News & Current Events":  "Learning",
    # Entertainment
    "Entertainment":          "Entertainment",
    "Comedy & Humor":         "Entertainment",
    "Music":                  "Entertainment",
    "Gaming":                 "Entertainment",
    "Art & Creativity":       "Entertainment",
    "Relationships":          "Entertainment",
    "Pets & Animals":         "Entertainment",
    # Finance
    "Finance & Money":        "Finance",
    "Career & Business":      "Finance",
    # Fashion
    "Fashion & Beauty":       "Fashion & Style",
    "Skincare":               "Fashion & Style",
    "Shopping":               "Fashion & Style",
}

# Keyword-based fallback: if the exact category key is not in the map,
# scan the category string for these keywords.
_KEYWORD_COLLECTION_MAP = [
    (["travel", "trip", "tour", "destination", "place", "visit", "explore"],        "Travel"),
    (["food", "recipe", "cook", "eat", "restaurant", "drink", "cuisine", "meal"],   "Food & Recipes"),
    (["fitness", "workout", "gym", "exercise", "health", "sport", "yoga", "run"],   "Fitness & Health"),
    (["tech", "software", "app", "code", "program", "ai", "device", "gadget"],      "Technology"),
    (["finance", "money", "invest", "budget", "crypto", "stock", "earn"],           "Finance"),
    (["fashion", "style", "outfit", "beauty", "makeup", "skin", "hair"],            "Fashion & Style"),
    (["learn", "educate", "study", "tutorial", "how-to", "craft", "diy", "tips"],  "Learning"),
    (["entertain", "music", "comedy", "fun", "game", "art", "movie", "show"],       "Entertainment"),
]

async def auto_assign_to_collection(item_id: str, user_id: str, ai_result: dict):
    try:
        category = ai_result.get("category", "")
        tags     = ai_result.get("tags", [])

        # 1. Exact map lookup
        target_name = CATEGORY_COLLECTION_MAP.get(category)

        # 2. Keyword fallback using category + sub_category + tags
        if not target_name:
            search_text = " ".join(
                [category, ai_result.get("sub_category", "")] + list(tags)
            ).lower()
            for keywords, coll_name in _KEYWORD_COLLECTION_MAP:
                if any(kw in search_text for kw in keywords):
                    target_name = coll_name
                    break

        if not target_name:
            return

        # 3. Find the collection (try exact match first, then partial)
        coll = await supabase.table("collections").select("id") \
            .eq("user_id", user_id).ilike("name", target_name).limit(1).execute()
        _coll = _first(coll)
        if not _coll:
            # Partial match — user may have renamed e.g. "Travel Bucket List"
            coll = await supabase.table("collections").select("id") \
                .eq("user_id", user_id).ilike("name", f"%{target_name}%").limit(1).execute()
            _coll = _first(coll)
        if not _coll:
            logger.info(f"No collection found for '{target_name}' (user {user_id})")
            return

        collection_id = _coll["id"]
        existing = await supabase.table("item_collection_map").select("id") \
            .eq("collection_id", collection_id).eq("item_id", item_id).limit(1).execute()
        if not existing.data:
            await supabase.table("item_collection_map").insert({
                "collection_id": collection_id,
                "item_id":       item_id,
                "added_at":      datetime.now(timezone.utc).isoformat(),
            }).execute()
            logger.info(f"Auto-assigned item {item_id} to collection '{target_name}'")
    except Exception as e:
        logger.warning(f"auto_assign_to_collection error: {e}")  # never crash the pipeline


# ─── Background Processing Pipeline ──────────────────────────────────────────
async def process_item(item_id: str, url: str, platform: str, user_id: str):
    def now(): return datetime.now(timezone.utc).isoformat()

    async def update_job(fields: dict):
        await supabase.table("processing_jobs").update(fields).eq("item_id", item_id).execute()

    async def update_item_fields(fields: dict):
        fields["updated_at"] = now()
        await supabase.table("items").update(fields).eq("id", item_id).execute()

    try:
        logger.info(f"Processing item {item_id} ({platform}): {url}")

        # ── Step 1: Metadata extraction ───────────────────────────────────────
        await update_job({"status": "running", "step_name": "metadata_extraction"})
        metadata = await extract_metadata(url, platform)
        logger.info(f"Metadata for {item_id}: '{metadata.get('title', 'N/A')}'")

        await update_item_fields({
            "title":         metadata.get("title", ""),
            "thumbnail_url": metadata.get("thumbnail_url", ""),
            "author":        metadata.get("author", ""),
            "duration":      metadata.get("duration", ""),
        })

        # Guard: empty metadata → treat as unavailable
        if (not metadata.get("title") and not metadata.get("description")
                and not metadata.get("thumbnail_url")):
            raise ContentUnavailableError(
                f"No content extracted from {url} — post may be deleted, private, or login-gated"
            )

        # ── Step 2: Vision analysis ───────────────────────────────────────────
        visual_text = ""
        thumb_urls  = metadata.get("thumbnail_urls", [])
        if not thumb_urls and metadata.get("thumbnail_url"):
            thumb_urls = [metadata["thumbnail_url"]]

        if thumb_urls:
            try:
                await update_job({"step_name": "vision_analysis"})
                from services.ai_service import analyze_thumbnails_with_vision
                visual_text = await analyze_thumbnails_with_vision(thumb_urls)
                if visual_text:
                    metadata["visual_text"] = visual_text
                    logger.info(f"Vision done for {item_id}: {len(visual_text)} chars")
            except Exception as e:
                logger.warning(f"Vision skipped for {item_id}: {e}")

        # ── Step 3: Audio transcript ──────────────────────────────────────────
        try:
            from services.extraction import extract_transcript_from_video
            await update_job({"step_name": "transcript_extraction"})
            transcript = await extract_transcript_from_video(url, platform)
            if transcript:
                metadata["transcript"] = transcript
                logger.info(f"Transcript for {item_id}: {len(transcript)} chars")
        except Exception as e:
            logger.warning(f"Transcript skipped for {item_id}: {e}")

        # ── Step 4: AI categorisation ─────────────────────────────────────────
        await update_job({"step_name": "ai_categorization"})
        ai_result = await asyncio.wait_for(categorize_content(metadata), timeout=60)
        logger.info(f"AI done for {item_id}: category={ai_result.get('category')}, "
                    f"key_points={len(ai_result.get('key_points', []))}, "
                    f"steps={len(ai_result.get('steps', []))}")

        await update_item_fields({
            "title":              ai_result.get("title") or metadata.get("title", "Untitled"),
            "summary":            ai_result.get("summary", ""),
            "key_points":         ai_result.get("key_points", []),
            "steps":              ai_result.get("steps", []),
            "ingredients":        ai_result.get("ingredients", []),
            "transcript_excerpt": ai_result.get("transcript_excerpt", ""),
            "visual_text":        (visual_text[:500] if visual_text else ""),
            "category":           ai_result.get("category", "Other"),
            "sub_category":       ai_result.get("sub_category", ""),
            "content_type":       ai_result.get("content_type", "general"),
            "tags":               ai_result.get("tags", []),
            "is_place_related":   ai_result.get("is_place_related", False),
            "confidence_score":   ai_result.get("confidence_score", 0.5),
            "source_status":      "completed",
        })

        # ── Step 4b: Embedding generation (for global chat vector search) ───────
        try:
            from services.ai_service import generate_embedding
            embed_text = " ".join(filter(None, [
                ai_result.get("title") or metadata.get("title", ""),
                ai_result.get("summary", ""),
                ai_result.get("category", ""),
                " ".join(ai_result.get("key_points", [])[:5]),
                ai_result.get("transcript_excerpt", "")[:300],
            ]))
            if embed_text.strip():
                embedding = await generate_embedding(embed_text)
                if embedding:
                    await update_item_fields({"embedding": embedding})
                    logger.info(f"Embedding stored for {item_id}")
        except Exception as e:
            logger.warning(f"Embedding generation skipped for {item_id}: {e}")

        # ── Step 5: Geocoding ─────────────────────────────────────────────────
        # Clear any previously-geocoded places for this item so retries don't
        # produce duplicates (e.g. the same hostel inserted twice on re-processing).
        try:
            await supabase.table("places").delete().eq("item_id", item_id).execute()
        except Exception as e:
            logger.warning(f"Could not clear existing places for {item_id}: {e}")

        if ai_result.get("is_place_related") and ai_result.get("places"):
            await update_job({"step_name": "geocoding"})
            # Build context hint for disambiguation (e.g. "Kyoto travel reel")
            item_context = " ".join(filter(None, [
                metadata.get("title", ""),
                ai_result.get("category", ""),
                ai_result.get("sub_category", ""),
            ]))[:120]

            # Deduplicate place entries (case-insensitive) within a single run
            seen_places = set()
            for place_entry in ai_result["places"][:15]:
                key = place_entry.strip().lower()
                if key in seen_places:
                    continue
                seen_places.add(key)
                display_name = (
                    place_entry.split(",")[0].strip() if "," in place_entry else place_entry
                )
                coords = await geocode_place(place_entry, context=item_context)
                if coords:
                    await supabase.table("places").insert({
                        "item_id":        item_id,
                        "name":           display_name,
                        "address":        coords.get("address", ""),
                        "latitude":       coords["lat"],
                        "longitude":      coords["lon"],
                        "geocode_source": coords.get("source", "nominatim"),
                        "created_at":     now(),
                    }).execute()

        # ── Step 6: Auto-assign to collection ────────────────────────────────
        await auto_assign_to_collection(item_id, user_id, ai_result)

        await update_job({"status": "completed", "step_name": "done", "completed_at": now()})
        logger.info(f"Processing complete for item {item_id}")

    except ContentUnavailableError as e:
        logger.warning(f"Content unavailable for {item_id}: {e}")
        n = now()
        await supabase.table("items").update({"source_status": "unavailable", "updated_at": n}).eq("id", item_id).execute()
        await supabase.table("processing_jobs").update(
            {"status": "unavailable", "error_message": str(e), "completed_at": n}
        ).eq("item_id", item_id).execute()

    except (asyncio.TimeoutError, Exception) as e:
        logger.error(f"Processing failed for {item_id}: {e}")
        n = now()
        await supabase.table("items").update({"source_status": "failed", "updated_at": n}).eq("id", item_id).execute()
        await supabase.table("processing_jobs").update(
            {"status": "failed", "error_message": str(e)[:500], "completed_at": n}
        ).eq("item_id", item_id).execute()


# ─── Items Routes ─────────────────────────────────────────────────────────────
@app.get("/api/items")
async def list_items(
    user:     dict         = Depends(get_current_user),
    category: Optional[str] = None,
    platform: Optional[str] = None,
    status:   Optional[str] = None,
    page:     int           = Query(1, ge=1),
    limit:    int           = Query(20, ge=1, le=100),
):
    skip  = (page - 1) * limit
    query = supabase.table("items").select("*", count="exact").eq("user_id", user["id"])

    if category: query = query.eq("category", category)
    if platform: query = query.eq("platform", platform)
    if status:   query = query.eq("source_status", status)

    result = await query.order("created_at", desc=True).range(skip, skip + limit - 1).execute()
    total  = result.count or 0

    return {
        "items": result.data,
        "total": total,
        "page":  page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


@app.get("/api/items/{item_id}")
async def get_item(item_id: str, user: dict = Depends(get_current_user)):
    res = await supabase.table("items").select("*") \
        .eq("id", item_id).eq("user_id", user["id"]).limit(1).execute()
    item = _first(res)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Places
    places_res      = await supabase.table("places").select("*").eq("item_id", item_id).execute()
    item["places"]  = places_res.data or []

    # Collections this item belongs to
    map_res = await supabase.table("item_collection_map").select("collection_id") \
        .eq("item_id", item_id).execute()
    collections = []
    for m in (map_res.data or []):
        cr = await supabase.table("collections").select("*") \
            .eq("id", m["collection_id"]).limit(1).execute()
        _cr = _first(cr)
        if _cr:
            collections.append(_cr)
    item["collections"] = collections

    # Processing job
    job_res = await supabase.table("processing_jobs").select("*") \
        .eq("item_id", item_id).limit(1).execute()
    _job = _first(job_res)
    if _job:
        item["processing"] = _job

    return item


@app.put("/api/items/{item_id}")
async def update_item(item_id: str, req: UpdateItemRequest,
                      user: dict = Depends(get_current_user)):
    chk = await supabase.table("items").select("id") \
        .eq("id", item_id).eq("user_id", user["id"]).limit(1).execute()
    if not _first(chk):
        raise HTTPException(status_code=404, detail="Item not found")

    fields: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if req.title        is not None: fields["title"]        = req.title
    if req.summary      is not None: fields["summary"]      = req.summary
    if req.category     is not None: fields["category"]     = req.category
    if req.sub_category is not None: fields["sub_category"] = req.sub_category
    if req.tags         is not None: fields["tags"]         = req.tags
    if req.notes        is not None: fields["notes"]        = req.notes
    if req.key_points   is not None: fields["key_points"]   = req.key_points
    if req.steps        is not None: fields["steps"]        = req.steps
    if req.ingredients  is not None: fields["ingredients"]  = req.ingredients

    updated = await supabase.table("items").update(fields).eq("id", item_id).execute()
    return updated.data[0] if updated.data else {}


@app.delete("/api/items/{item_id}")
async def delete_item(item_id: str, user: dict = Depends(get_current_user)):
    chk = await supabase.table("items").select("id") \
        .eq("id", item_id).eq("user_id", user["id"]).limit(1).execute()
    if not _first(chk):
        raise HTTPException(status_code=404, detail="Item not found")

    await supabase.table("places").delete().eq("item_id", item_id).execute()
    await supabase.table("item_collection_map").delete().eq("item_id", item_id).execute()
    await supabase.table("processing_jobs").delete().eq("item_id", item_id).execute()
    await supabase.table("items").delete().eq("id", item_id).execute()
    return {"message": "Item deleted"}


# ─── Collections Routes ──────────────────────────────────────────────────────
@app.post("/api/collections")
async def create_collection(req: CreateCollectionRequest,
                            user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    res = await supabase.table("collections").insert({
        "user_id":     user["id"],
        "name":        req.name,
        "description": req.description or "",
        "created_at":  now,
        "updated_at":  now,
    }).execute()
    return res.data[0]


@app.get("/api/collections")
async def list_collections(user: dict = Depends(get_current_user)):
    res = await supabase.table("collections").select("*") \
        .eq("user_id", user["id"]).order("created_at", desc=True).execute()
    collections = []
    for coll in (res.data or []):
        cnt = await supabase.table("item_collection_map").select("*", count="exact") \
            .eq("collection_id", coll["id"]).execute()
        coll["item_count"] = cnt.count or 0
        collections.append(coll)
    return {"collections": collections}


@app.get("/api/collections/{collection_id}")
async def get_collection(collection_id: str, user: dict = Depends(get_current_user)):
    res = await supabase.table("collections").select("*") \
        .eq("id", collection_id).eq("user_id", user["id"]).limit(1).execute()
    coll = _first(res)
    if not coll:
        raise HTTPException(status_code=404, detail="Collection not found")

    map_res = await supabase.table("item_collection_map").select("item_id") \
        .eq("collection_id", collection_id).execute()
    items = []
    for m in (map_res.data or []):
        ir = await supabase.table("items").select("*") \
            .eq("id", m["item_id"]).limit(1).execute()
        _ir = _first(ir)
        if _ir:
            items.append(_ir)
    coll["items"]      = items
    coll["item_count"] = len(items)
    return coll


@app.put("/api/collections/{collection_id}")
async def update_collection(collection_id: str, req: CreateCollectionRequest,
                            user: dict = Depends(get_current_user)):
    chk = await supabase.table("collections").select("id") \
        .eq("id", collection_id).eq("user_id", user["id"]).limit(1).execute()
    if not _first(chk):
        raise HTTPException(status_code=404, detail="Collection not found")
    updated = await supabase.table("collections").update({
        "name":        req.name,
        "description": req.description or "",
        "updated_at":  datetime.now(timezone.utc).isoformat(),
    }).eq("id", collection_id).execute()
    return updated.data[0] if updated.data else {}


@app.delete("/api/collections/{collection_id}")
async def delete_collection(collection_id: str, user: dict = Depends(get_current_user)):
    chk = await supabase.table("collections").select("id") \
        .eq("id", collection_id).eq("user_id", user["id"]).limit(1).execute()
    if not _first(chk):
        raise HTTPException(status_code=404, detail="Collection not found")
    await supabase.table("item_collection_map").delete().eq("collection_id", collection_id).execute()
    await supabase.table("collections").delete().eq("id", collection_id).execute()
    return {"message": "Collection deleted"}


@app.get("/api/collections/{collection_id}/available-items")
async def get_available_items(collection_id: str, user: dict = Depends(get_current_user)):
    res = await supabase.table("collections").select("id, name") \
        .eq("id", collection_id).eq("user_id", user["id"]).limit(1).execute()
    _res = _first(res)
    if not _res:
        raise HTTPException(status_code=404, detail="Collection not found")

    map_res  = await supabase.table("item_collection_map").select("item_id") \
        .eq("collection_id", collection_id).execute()
    in_coll  = {m["item_id"] for m in (map_res.data or [])}

    items_res = await supabase.table("items").select("*") \
        .eq("user_id", user["id"]).eq("source_status", "completed") \
        .order("created_at", desc=True).limit(200).execute()
    items = []
    for item in (items_res.data or []):
        item["in_collection"] = item["id"] in in_coll
        items.append(item)
    return {"items": items, "collection_name": _res["name"]}


@app.post("/api/collections/{collection_id}/items")
async def add_item_to_collection(collection_id: str, req: AddItemToCollectionRequest,
                                 user: dict = Depends(get_current_user)):
    coll_chk = await supabase.table("collections").select("id") \
        .eq("id", collection_id).eq("user_id", user["id"]).limit(1).execute()
    if not _first(coll_chk):
        raise HTTPException(status_code=404, detail="Collection not found")
    item_chk = await supabase.table("items").select("id") \
        .eq("id", req.item_id).eq("user_id", user["id"]).limit(1).execute()
    if not _first(item_chk):
        raise HTTPException(status_code=404, detail="Item not found")
    existing = await supabase.table("item_collection_map").select("id") \
        .eq("collection_id", collection_id).eq("item_id", req.item_id).limit(1).execute()
    if _first(existing):
        return {"message": "Item already in collection"}
    await supabase.table("item_collection_map").insert({
        "collection_id": collection_id,
        "item_id":       req.item_id,
        "added_at":      datetime.now(timezone.utc).isoformat(),
    }).execute()
    return {"message": "Item added to collection"}


@app.delete("/api/collections/{collection_id}/items/{item_id}")
async def remove_item_from_collection(collection_id: str, item_id: str,
                                      user: dict = Depends(get_current_user)):
    coll_chk = await supabase.table("collections").select("id") \
        .eq("id", collection_id).eq("user_id", user["id"]).limit(1).execute()
    if not _first(coll_chk):
        raise HTTPException(status_code=404, detail="Collection not found")
    await supabase.table("item_collection_map").delete() \
        .eq("collection_id", collection_id).eq("item_id", item_id).execute()
    return {"message": "Item removed from collection"}


# ─── Search Routes ────────────────────────────────────────────────────────────
@app.get("/api/search")
async def search_items(
    q:             str           = "",
    category:      Optional[str] = None,
    platform:      Optional[str] = None,
    collection_id: Optional[str] = None,
    tag:           Optional[str] = None,
    page:          int           = Query(1, ge=1),
    limit:         int           = Query(20, ge=1, le=100),
    user:          dict          = Depends(get_current_user),
):
    skip  = (page - 1) * limit
    query = supabase.table("items").select("*", count="exact").eq("user_id", user["id"])

    if category: query = query.ilike("category", f"%{category}%")
    if platform: query = query.eq("platform", platform)

    if q:
        # Full-text search across title, summary, category, notes via ILIKE
        safe_q = q.replace("%", "\\%").replace("_", "\\_")
        query  = query.or_(
            f"title.ilike.%{safe_q}%,"
            f"summary.ilike.%{safe_q}%,"
            f"category.ilike.%{safe_q}%,"
            f"notes.ilike.%{safe_q}%"
        )

    # Collection filter: fetch item IDs first
    if collection_id:
        map_res  = await supabase.table("item_collection_map").select("item_id") \
            .eq("collection_id", collection_id).execute()
        item_ids = [m["item_id"] for m in (map_res.data or [])]
        if not item_ids:
            return {"items": [], "total": 0, "page": page, "query": q}
        query = query.in_("id", item_ids)

    result = await query.order("created_at", desc=True).range(skip, skip + limit - 1).execute()
    items  = result.data or []
    total  = result.count or 0

    # Tag filter (post-filter; JSONB array contains is complex in PostgREST)
    if tag:
        items = [item for item in items if tag in (item.get("tags") or [])]

    return {"items": items, "total": total, "page": page, "query": q}


# ─── Map Routes ───────────────────────────────────────────────────────────────
@app.get("/api/map")
async def get_map_items(
    user:     dict         = Depends(get_current_user),
    category: Optional[str] = None,
):
    query = supabase.table("items").select("*") \
        .eq("user_id", user["id"]).eq("is_place_related", True)
    if category:
        query = query.eq("category", category)
    items_res  = await query.execute()

    map_items  = []
    for item in (items_res.data or []):
        places_res = await supabase.table("places").select("*").eq("item_id", item["id"]).execute()
        if places_res.data:
            item["places"] = places_res.data
            map_items.append(item)
    return {"items": map_items}


# ─── Categories Route ─────────────────────────────────────────────────────────
@app.get("/api/categories")
async def get_categories(user: dict = Depends(get_current_user)):
    res    = await supabase.table("items").select("category") \
        .eq("user_id", user["id"]).neq("category", "").execute()
    counts = Counter(item["category"] for item in (res.data or []) if item.get("category"))
    return {"categories": [{"name": cat, "count": cnt} for cat, cnt in counts.most_common()]}


# ─── Retry Processing ─────────────────────────────────────────────────────────
@app.post("/api/items/{item_id}/retry")
async def retry_processing(item_id: str, background_tasks: BackgroundTasks,
                           user: dict = Depends(get_current_user)):
    res = await supabase.table("items").select("*") \
        .eq("id", item_id).eq("user_id", user["id"]).limit(1).execute()
    item = _first(res)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    retry_count = item.get("retry_count", 0)
    if retry_count >= MAX_RETRIES:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum retries ({MAX_RETRIES}) reached for this item.",
        )

    current_status = item.get("source_status")
    stuck          = False
    if current_status == "processing":
        updated_at = item.get("updated_at")
        if updated_at:
            try:
                dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                stuck = (datetime.now(timezone.utc) - dt).total_seconds() > 600
            except Exception:
                pass
        if not stuck:
            raise HTTPException(status_code=400, detail="Item is already being processed")

    if current_status not in ["failed", "completed", "unavailable"] and not stuck:
        raise HTTPException(status_code=400, detail="Item is already being processed")

    now_str = datetime.now(timezone.utc).isoformat()
    await supabase.table("items").update({
        "source_status": "processing",
        "retry_count":   retry_count + 1,
        "updated_at":    now_str,
    }).eq("id", item_id).execute()

    # Upsert the processing job
    job_res = await supabase.table("processing_jobs").select("id") \
        .eq("item_id", item_id).limit(1).execute()
    job_fields = {
        "status": "pending", "step_name": "metadata_extraction",
        "error_message": "", "started_at": now_str, "completed_at": None,
    }
    if _first(job_res):
        await supabase.table("processing_jobs").update(job_fields).eq("item_id", item_id).execute()
    else:
        await supabase.table("processing_jobs").insert(
            {"item_id": item_id, **job_fields}
        ).execute()

    background_tasks.add_task(process_item, item_id, item["url"], item["platform"], user["id"])
    return {
        "message":          "Processing restarted",
        "retry_count":      retry_count + 1,
        "retries_remaining": MAX_RETRIES - retry_count - 1,
    }


# ── Place correction ──────────────────────────────────────────────────────────

class PlaceCorrectionRequest(BaseModel):
    address_override: str

@app.put("/api/places/{place_id}")
async def correct_place(
    place_id: str,
    body: PlaceCorrectionRequest,
    user: dict = Depends(get_current_user),
):
    """
    Re-geocode a place using a user-supplied address override.
    Uses HERE Geocoding when available; falls back to Nominatim.
    Ownership is verified via the parent item's user_id.
    """
    address = body.address_override.strip()
    if not address:
        raise HTTPException(status_code=400, detail="address_override is required")

    # Verify ownership: the place must belong to one of this user's items
    place_res = await supabase.table("places").select("*, items(user_id)") \
        .eq("id", place_id).limit(1).execute()
    place = _first(place_res)
    if not place:
        raise HTTPException(status_code=404, detail="Place not found")

    owner_id = (place.get("items") or {}).get("user_id")
    if owner_id != user["id"]:
        raise HTTPException(status_code=403, detail="Not your place")

    # Re-geocode with the user-supplied address
    from services.geocoding import _nominatim_search
    from services.place_search import _here_geocode
    import os

    coords = None
    source = "nominatim"

    if os.getenv("HERE_API_KEY"):
        coords = await _here_geocode(address)
        if coords:
            source = "here_override"

    if not coords:
        coords = await _nominatim_search(address)
        if coords:
            source = "nominatim_override"

    if not coords:
        raise HTTPException(status_code=422, detail=f"Could not geocode address: {address!r}")

    updated = {
        "address":        coords.get("address", address),
        "latitude":       coords["lat"],
        "longitude":      coords["lon"],
        "geocode_source": source,
    }
    await supabase.table("places").update(updated).eq("id", place_id).execute()

    return {"id": place_id, **updated}


# ── Chat endpoints (Phase 4) ──────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str     # "user" | "assistant"
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]


@app.post("/api/chat/item/{item_id}")
async def chat_with_item(
    item_id: str,
    body: ChatRequest,
    user: dict = Depends(get_current_user),
):
    """Stream a per-item chat response grounded in the saved item's content."""
    # Fetch item (verifies ownership)
    item_res = await supabase.table("items").select("*") \
        .eq("id", item_id).eq("user_id", user["id"]).limit(1).execute()
    item = _first(item_res)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Also fetch places so the chatbot knows about them
    places_res = await supabase.table("places").select("name, address") \
        .eq("item_id", item_id).execute()
    item = dict(item)
    item["places"] = places_res.data or []

    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    from services.chat_service import item_chat
    stream_gen = await item_chat(item, messages)

    return StreamingResponse(
        stream_gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat/library")
async def chat_with_library(
    body: ChatRequest,
    user: dict = Depends(get_current_user),
):
    """Stream a library-wide chat response using semantic search across all saved items."""
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    from services.chat_service import library_chat
    stream_gen = await library_chat(messages, user["id"], supabase)

    return StreamingResponse(
        stream_gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Hype endpoints (Phase 5) ──────────────────────────────────────────────────

def _migration_needed_error():
    raise HTTPException(
        status_code=503,
        detail=(
            "Hype tables not set up yet. "
            "Run scripts/create_hype_tables.sql in the Supabase SQL editor: "
            "https://supabase.com/dashboard/project/foktswfeqhzpyrbxzrkm/sql/new"
        ),
    )


@app.post("/api/items/{item_id}/hype")
async def hype_item(item_id: str, user: dict = Depends(get_current_user)):
    """Add a hype for an item. Idempotent — re-hyping the same item is a no-op."""
    try:
        item_res = await supabase.table("items").select("id, user_id") \
            .eq("id", item_id).limit(1).execute()
        if not _first(item_res):
            raise HTTPException(status_code=404, detail="Item not found")

        try:
            await supabase.table("hypes").insert({
                "item_id": item_id,
                "user_id": user["id"],
            }).execute()
        except Exception as e:
            err = str(e).lower()
            if "duplicate" in err or "23505" in err:
                pass  # Already hyped — idempotent
            elif "relation" in err and "hypes" in err:
                _migration_needed_error()
            else:
                raise HTTPException(status_code=500, detail=str(e))

        updated = await supabase.table("items").select("hype_count") \
            .eq("id", item_id).limit(1).execute()
        hype_count = (_first(updated) or {}).get("hype_count", 0)
        return {"item_id": item_id, "hype_count": hype_count, "hyped": True}
    except HTTPException:
        raise
    except Exception as e:
        if "hype_count" in str(e) or "is_public" in str(e):
            _migration_needed_error()
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/items/{item_id}/hype")
async def unhype_item(item_id: str, user: dict = Depends(get_current_user)):
    """Remove a hype (un-hype). Idempotent."""
    try:
        await supabase.table("hypes") \
            .delete() \
            .eq("item_id", item_id) \
            .eq("user_id", user["id"]) \
            .execute()
        updated = await supabase.table("items").select("hype_count") \
            .eq("id", item_id).limit(1).execute()
        hype_count = (_first(updated) or {}).get("hype_count", 0)
        return {"item_id": item_id, "hype_count": hype_count, "hyped": False}
    except HTTPException:
        raise
    except Exception as e:
        err = str(e).lower()
        if ("relation" in err and "hypes" in err) or "hype_count" in err:
            _migration_needed_error()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/items/{item_id}/hype")
async def get_hype_status(item_id: str, user: dict = Depends(get_current_user)):
    """Return current hype_count and whether the current user has hyped this item."""
    try:
        item_res = await supabase.table("items").select("id") \
            .eq("id", item_id).limit(1).execute()
        if not _first(item_res):
            raise HTTPException(status_code=404, detail="Item not found")

        # If hypes table doesn't exist yet, return defaults instead of crashing
        try:
            hype_res = await supabase.table("hypes").select("item_id") \
                .eq("item_id", item_id).eq("user_id", user["id"]).limit(1).execute()
        except Exception:
            return {"item_id": item_id, "hype_count": 0, "hyped": False}

        try:
            count_res = await supabase.table("items").select("hype_count") \
                .eq("id", item_id).limit(1).execute()
            hype_count = (_first(count_res) or {}).get("hype_count", 0)
        except Exception:
            hype_count = 0

        return {
            "item_id":    item_id,
            "hype_count": hype_count,
            "hyped":      bool(hype_res.data),
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"item_id": item_id, "hype_count": 0, "hyped": False}


@app.get("/api/trending")
async def get_trending(
    category: str = Query(default=""),
    period:   str = Query(default="week"),   # "day" | "week" | "all"
    limit:    int = Query(default=20, le=50),
    page:     int = Query(default=1, ge=1),
    user: dict = Depends(get_current_user),
):
    """Return publicly hyped items sorted by hype_count (cross-user trending feed)."""
    skip = (page - 1) * limit

    try:
        query = supabase.table("items") \
            .select("*", count="exact") \
            .eq("is_public", True) \
            .gt("hype_count", 0) \
            .order("hype_count", desc=True)

        if period == "day":
            since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            query = query.gte("updated_at", since)
        elif period == "week":
            since = (datetime.now(timezone.utc) - timedelta(weeks=1)).isoformat()
            query = query.gte("updated_at", since)

        if category:
            query = query.ilike("category", f"%{category}%")

        res = await query.range(skip, skip + limit - 1).execute()
        items = res.data or []
        total = res.count or 0

        if items:
            item_ids = [it["id"] for it in items]
            try:
                hype_res = await supabase.table("hypes").select("item_id") \
                    .eq("user_id", user["id"]) \
                    .in_("item_id", item_ids) \
                    .execute()
                hyped_ids = {h["item_id"] for h in (hype_res.data or [])}
            except Exception:
                hyped_ids = set()
            for it in items:
                it["user_hyped"] = it["id"] in hyped_ids
                it.pop("embedding", None)
                it.pop("notes", None)

        return {
            "items":             items,
            "total":             total,
            "page":              page,
            "pages":             (total + limit - 1) // limit if total else 1,
            "migration_pending": False,
        }

    except Exception as e:
        err = str(e).lower()
        # Only flag migration_pending if the error clearly indicates a missing
        # column/table — otherwise surface the real error so we don't silently
        # hide unrelated failures (e.g. malformed queries).
        looks_like_missing_schema = (
            ("column" in err and ("hype_count" in err or "is_public" in err))
            or "relation" in err and "does not exist" in err
            or "pgrst204" in err
        )
        if looks_like_missing_schema:
            return {
                "items":             [],
                "total":             0,
                "page":              1,
                "pages":             1,
                "migration_pending": True,
                "migration_hint":    (
                    "Run scripts/create_hype_tables.sql in the Supabase SQL editor: "
                    "https://supabase.com/dashboard/project/foktswfeqhzpyrbxzrkm/sql/new"
                ),
            }
        logger.error(f"Trending query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Trending query failed: {e}")
