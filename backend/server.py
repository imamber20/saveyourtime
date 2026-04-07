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
from fastapi import FastAPI, HTTPException, Request, Response, Depends, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import acreate_client, AsyncClient

from services.extraction import (
    validate_url, detect_platform, extract_metadata,
    ContentUnavailableError, quick_availability_check,
)
from services.ai_service import categorize_content
from services.geocoding import geocode_place

MAX_RETRIES = 3

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
            .maybe_single().execute()
        if not existing.data:
            await supabase.table("collections").insert({
                "user_id": user_id,
                "name": coll["name"],
                "description": coll["description"],
                "created_at": now,
                "updated_at": now,
            }).execute()


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
                # Exists but wrong password — reset it to the configured value
                admin_id = existing_admin.id
                await supabase.auth.admin.update_user_by_id(
                    admin_id, {"password": ADMIN_PASSWORD}
                )
                logger.info(f"Admin password reset to configured value: {ADMIN_EMAIL}")
            else:
                # Truly new — create from scratch
                res      = await supabase.auth.admin.create_user({
                    "email":         ADMIN_EMAIL,
                    "password":      ADMIN_PASSWORD,
                    "email_confirm": True,
                    "user_metadata": {"name": "Admin", "role": "admin"},
                })
                admin_id = res.user.id
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
    try:
        res = await supabase.auth.admin.create_user({
            "email": email,
            "password": req.password,
            "email_confirm": True,
            "user_metadata": {"name": req.name},
        })
        user_id = res.user.id
    except Exception as e:
        msg = str(e).lower()
        if any(x in msg for x in ("already registered", "already exists", "unique", "duplicate")):
            raise HTTPException(status_code=400, detail="Email already registered")
        raise HTTPException(status_code=400, detail=f"Registration failed: {e}")

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
        .eq("id", user_id).maybe_single().execute()
    role = (prof.data or {}).get("role", "user")
    if not name:
        name = (prof.data or {}).get("name", "")

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
        .eq("id", user["id"]).maybe_single().execute()
    if prof.data:
        user["name"] = prof.data.get("name", "")
        user["role"] = prof.data.get("role", "user")
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

    # Fast availability pre-check
    check = await quick_availability_check(url)
    if not check["available"] and check.get("reason") != "timeout":
        raise HTTPException(
            status_code=422,
            detail={"type": "unavailable",
                    "reason": check["reason"] or "Content not found or no longer accessible"},
        )

    # Duplicate check
    dup = await supabase.table("items").select("id") \
        .eq("url", url).eq("user_id", user["id"]).maybe_single().execute()
    if dup.data:
        return {"item_id": dup.data["id"], "status": "duplicate",
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
    "Fitness & Health":     "Fitness & Health",
    "Sports":               "Fitness & Health",
    "Travel":               "Travel",
    "Nature & Outdoors":    "Travel",
    "Food & Recipes":       "Food & Recipes",
    "Technology":           "Technology",
    "Education & Learning": "Learning",
    "DIY & Crafts":         "Learning",
    "Entertainment":        "Entertainment",
    "Comedy & Humor":       "Entertainment",
    "Music":                "Entertainment",
    "Gaming":               "Entertainment",
    "Art & Creativity":     "Entertainment",
    "Finance & Money":      "Finance",
    "Career & Business":    "Finance",
    "Fashion & Beauty":     "Fashion & Style",
    "Skincare":             "Fashion & Style",
    "Shopping":             "Fashion & Style",
    "Parenting":            "Learning",
    "Motivation":           "Learning",
    "Relationships":        "Entertainment",
    "Pets & Animals":       "Entertainment",
}

async def auto_assign_to_collection(item_id: str, user_id: str, ai_result: dict):
    try:
        target_name = CATEGORY_COLLECTION_MAP.get(ai_result.get("category", ""))
        if not target_name:
            return
        coll = await supabase.table("collections").select("id") \
            .eq("user_id", user_id).ilike("name", target_name).maybe_single().execute()
        if not coll.data:
            return
        collection_id = coll.data["id"]
        existing = await supabase.table("item_collection_map").select("id") \
            .eq("collection_id", collection_id).eq("item_id", item_id).maybe_single().execute()
        if not existing.data:
            await supabase.table("item_collection_map").insert({
                "collection_id": collection_id,
                "item_id":       item_id,
                "added_at":      datetime.now(timezone.utc).isoformat(),
            }).execute()
            logger.info(f"Auto-assigned item {item_id} to collection '{target_name}'")
    except Exception:
        pass  # never crash the pipeline


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
            "tags":               ai_result.get("tags", []),
            "is_place_related":   ai_result.get("is_place_related", False),
            "confidence_score":   ai_result.get("confidence_score", 0.5),
            "source_status":      "completed",
        })

        # ── Step 5: Geocoding ─────────────────────────────────────────────────
        if ai_result.get("is_place_related") and ai_result.get("places"):
            await update_job({"step_name": "geocoding"})
            for place_entry in ai_result["places"][:5]:
                display_name = (
                    place_entry.split(",")[0].strip() if "," in place_entry else place_entry
                )
                coords = await geocode_place(place_entry)
                if coords:
                    await supabase.table("places").insert({
                        "item_id":       item_id,
                        "name":          display_name,
                        "address":       coords.get("address", ""),
                        "latitude":      coords["lat"],
                        "longitude":     coords["lon"],
                        "geocode_source": "nominatim",
                        "created_at":    now(),
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
        .eq("id", item_id).eq("user_id", user["id"]).maybe_single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Item not found")
    item = res.data

    # Places
    places_res      = await supabase.table("places").select("*").eq("item_id", item_id).execute()
    item["places"]  = places_res.data or []

    # Collections this item belongs to
    map_res = await supabase.table("item_collection_map").select("collection_id") \
        .eq("item_id", item_id).execute()
    collections = []
    for m in (map_res.data or []):
        cr = await supabase.table("collections").select("*") \
            .eq("id", m["collection_id"]).maybe_single().execute()
        if cr.data:
            collections.append(cr.data)
    item["collections"] = collections

    # Processing job
    job_res = await supabase.table("processing_jobs").select("*") \
        .eq("item_id", item_id).maybe_single().execute()
    if job_res.data:
        item["processing"] = job_res.data

    return item


@app.put("/api/items/{item_id}")
async def update_item(item_id: str, req: UpdateItemRequest,
                      user: dict = Depends(get_current_user)):
    chk = await supabase.table("items").select("id") \
        .eq("id", item_id).eq("user_id", user["id"]).maybe_single().execute()
    if not chk.data:
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
        .eq("id", item_id).eq("user_id", user["id"]).maybe_single().execute()
    if not chk.data:
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
        .eq("id", collection_id).eq("user_id", user["id"]).maybe_single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Collection not found")
    coll = res.data

    map_res = await supabase.table("item_collection_map").select("item_id") \
        .eq("collection_id", collection_id).execute()
    items = []
    for m in (map_res.data or []):
        ir = await supabase.table("items").select("*") \
            .eq("id", m["item_id"]).maybe_single().execute()
        if ir.data:
            items.append(ir.data)
    coll["items"]      = items
    coll["item_count"] = len(items)
    return coll


@app.put("/api/collections/{collection_id}")
async def update_collection(collection_id: str, req: CreateCollectionRequest,
                            user: dict = Depends(get_current_user)):
    chk = await supabase.table("collections").select("id") \
        .eq("id", collection_id).eq("user_id", user["id"]).maybe_single().execute()
    if not chk.data:
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
        .eq("id", collection_id).eq("user_id", user["id"]).maybe_single().execute()
    if not chk.data:
        raise HTTPException(status_code=404, detail="Collection not found")
    await supabase.table("item_collection_map").delete().eq("collection_id", collection_id).execute()
    await supabase.table("collections").delete().eq("id", collection_id).execute()
    return {"message": "Collection deleted"}


@app.get("/api/collections/{collection_id}/available-items")
async def get_available_items(collection_id: str, user: dict = Depends(get_current_user)):
    res = await supabase.table("collections").select("id, name") \
        .eq("id", collection_id).eq("user_id", user["id"]).maybe_single().execute()
    if not res.data:
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
    return {"items": items, "collection_name": res.data["name"]}


@app.post("/api/collections/{collection_id}/items")
async def add_item_to_collection(collection_id: str, req: AddItemToCollectionRequest,
                                 user: dict = Depends(get_current_user)):
    coll_chk = await supabase.table("collections").select("id") \
        .eq("id", collection_id).eq("user_id", user["id"]).maybe_single().execute()
    if not coll_chk.data:
        raise HTTPException(status_code=404, detail="Collection not found")
    item_chk = await supabase.table("items").select("id") \
        .eq("id", req.item_id).eq("user_id", user["id"]).maybe_single().execute()
    if not item_chk.data:
        raise HTTPException(status_code=404, detail="Item not found")
    existing = await supabase.table("item_collection_map").select("id") \
        .eq("collection_id", collection_id).eq("item_id", req.item_id).maybe_single().execute()
    if existing.data:
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
        .eq("id", collection_id).eq("user_id", user["id"]).maybe_single().execute()
    if not coll_chk.data:
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
        .eq("id", item_id).eq("user_id", user["id"]).maybe_single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Item not found")
    item = res.data

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
        .eq("item_id", item_id).maybe_single().execute()
    job_fields = {
        "status": "pending", "step_name": "metadata_extraction",
        "error_message": "", "started_at": now_str, "completed_at": None,
    }
    if job_res.data:
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
