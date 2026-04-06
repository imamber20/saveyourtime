from dotenv import load_dotenv
load_dotenv()

import os
import re
import json
import asyncio
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from contextlib import asynccontextmanager

import bcrypt
import jwt as pyjwt
from bson import ObjectId
from fastapi import FastAPI, HTTPException, Request, Response, Depends, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

from services.extraction import validate_url, detect_platform, extract_metadata, ContentUnavailableError, quick_availability_check
from services.ai_service import categorize_content
from services.geocoding import geocode_place

MAX_RETRIES = 3  # hard cap on how many times a single item can be reprocessed

# ─── Config ───────────────────────────────────────────────────────────────────
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "content_memory")
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower().strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("content_memory")

# ─── Database ─────────────────────────────────────────────────────────────────
client: AsyncIOMotorClient = None
db = None

async def get_db():
    return db

# ─── Password Hashing ────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

# ─── JWT ──────────────────────────────────────────────────────────────────────
def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id, "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=60),
        "type": "access"
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh"
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def set_auth_cookies(response: Response, access_token: str, refresh_token: str):
    response.set_cookie(key="access_token", value=access_token, httponly=True, secure=False, samesite="lax", max_age=3600, path="/")
    response.set_cookie(key="refresh_token", value=refresh_token, httponly=True, secure=False, samesite="lax", max_age=604800, path="/")

# ─── Auth Dependency ──────────────────────────────────────────────────────────
async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        user = serialize_doc(user)
        user.pop("password_hash", None)
        return user
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ─── Pydantic Schemas ────────────────────────────────────────────────────────
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
    title: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    sub_category: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    key_points: Optional[List[str]] = None
    steps: Optional[List[str]] = None
    ingredients: Optional[List[str]] = None

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

# ─── Helpers ──────────────────────────────────────────────────────────────────
def serialize_doc(doc):
    if doc is None:
        return None
    doc["id"] = str(doc.pop("_id"))
    for key, val in doc.items():
        if isinstance(val, ObjectId):
            doc[key] = str(val)
        if isinstance(val, datetime):
            doc[key] = val.isoformat()
    return doc

async def check_brute_force(identifier: str):
    attempt = await db.login_attempts.find_one({"identifier": identifier})
    if attempt and attempt.get("count", 0) >= 5:
        last = attempt.get("last_attempt", datetime.now(timezone.utc))
        if datetime.now(timezone.utc) - last < timedelta(minutes=15):
            raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes.")

async def record_failed_attempt(identifier: str):
    await db.login_attempts.update_one(
        {"identifier": identifier},
        {"$inc": {"count": 1}, "$set": {"last_attempt": datetime.now(timezone.utc)}},
        upsert=True
    )

async def clear_failed_attempts(identifier: str):
    await db.login_attempts.delete_one({"identifier": identifier})

# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global client, db
    client = AsyncIOMotorClient(MONGO_URL, tz_aware=True)
    db = client[DB_NAME]

    # Create indexes
    await db.users.create_index("email", unique=True)
    await db.items.create_index([("title", "text"), ("summary", "text"), ("tags", "text"), ("category", "text"), ("notes", "text")])
    await db.items.create_index("user_id")
    await db.items.create_index("platform")
    await db.items.create_index("category")
    await db.items.create_index("created_at")
    await db.collections.create_index("user_id")
    await db.item_collection_map.create_index([("collection_id", 1), ("item_id", 1)], unique=True)
    await db.places.create_index("item_id")
    await db.processing_jobs.create_index("item_id")
    await db.login_attempts.create_index("identifier")
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)

    # Seed admin
    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if not existing:
        ins = await db.users.insert_one({
            "email": ADMIN_EMAIL,
            "password_hash": hash_password(ADMIN_PASSWORD),
            "name": "Admin",
            "role": "admin",
            "created_at": datetime.now(timezone.utc)
        })
        await seed_default_collections(str(ins.inserted_id))
        logger.info(f"Admin user seeded: {ADMIN_EMAIL}")
    else:
        if not verify_password(ADMIN_PASSWORD, existing["password_hash"]):
            await db.users.update_one({"email": ADMIN_EMAIL}, {"$set": {"password_hash": hash_password(ADMIN_PASSWORD)}})
        # Seed collections for existing admin if missing
        await seed_default_collections(str(existing["_id"]))

    # Write test credentials
    _memory_dir = os.environ.get("MEMORY_DIR", os.path.join(os.path.dirname(__file__), "..", "memory"))
    os.makedirs(_memory_dir, exist_ok=True)
    with open(os.path.join(_memory_dir, "test_credentials.md"), "w") as f:
        f.write("# Test Credentials\n\n")
        f.write(f"## Admin\n- Email: {ADMIN_EMAIL}\n- Password: {ADMIN_PASSWORD}\n- Role: admin\n\n")
        f.write("## Auth Endpoints\n")
        f.write("- POST /api/auth/register\n- POST /api/auth/login\n- POST /api/auth/logout\n")
        f.write("- GET /api/auth/me\n- POST /api/auth/refresh\n")

    logger.info("Content Memory API started")
    yield
    client.close()

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
    return {"status": "ok", "service": "content-memory", "timestamp": datetime.now(timezone.utc).isoformat()}

# ─── Auth Routes ──────────────────────────────────────────────────────────────
DEFAULT_COLLECTIONS = [
    {"name": "Fitness & Health",   "description": "Workouts, wellness tips, and health routines"},
    {"name": "Travel",             "description": "Places to visit, travel tips, and destination guides"},
    {"name": "Food & Recipes",     "description": "Recipes, cooking techniques, and restaurant finds"},
    {"name": "Technology",         "description": "Tech tutorials, gadget reviews, and digital tips"},
    {"name": "Learning",           "description": "Educational content, how-tos, and skill-building"},
    {"name": "Entertainment",      "description": "Fun videos, comedy, music, and pop culture"},
    {"name": "Finance",            "description": "Money tips, investing advice, and personal finance"},
    {"name": "Fashion & Style",    "description": "Outfits, beauty tips, skincare, and shopping picks"},
]

async def seed_default_collections(user_id: str):
    """Create default collections for a new user if they don't already exist."""
    now = datetime.now(timezone.utc)
    for coll in DEFAULT_COLLECTIONS:
        existing = await db.collections.find_one({"user_id": user_id, "name": coll["name"]})
        if not existing:
            await db.collections.insert_one({
                "user_id": user_id,
                "name": coll["name"],
                "description": coll["description"],
                "created_at": now,
                "updated_at": now,
            })

@app.post("/api/auth/register")
async def register(req: RegisterRequest, response: Response, background_tasks: BackgroundTasks):
    email = req.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    user_doc = {
        "email": email,
        "password_hash": hash_password(req.password),
        "name": req.name,
        "role": "user",
        "created_at": datetime.now(timezone.utc)
    }
    result = await db.users.insert_one(user_doc)
    user_id = str(result.inserted_id)
    access_token = create_access_token(user_id, email)
    refresh_token = create_refresh_token(user_id)
    set_auth_cookies(response, access_token, refresh_token)
    background_tasks.add_task(seed_default_collections, user_id)
    return {"id": user_id, "email": email, "name": req.name, "role": "user"}

@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request, response: Response):
    email = req.email.lower().strip()
    ip = request.client.host if request.client else "unknown"
    identifier = f"{ip}:{email}"
    await check_brute_force(identifier)
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(req.password, user["password_hash"]):
        await record_failed_attempt(identifier)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    await clear_failed_attempts(identifier)
    user_id = str(user["_id"])
    access_token = create_access_token(user_id, email)
    refresh_token = create_refresh_token(user_id)
    set_auth_cookies(response, access_token, refresh_token)
    return {"id": user_id, "email": email, "name": user.get("name", ""), "role": user.get("role", "user")}

@app.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"message": "Logged out"}

@app.get("/api/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return user

@app.post("/api/auth/refresh")
async def refresh(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        user_id = str(user["_id"])
        new_access = create_access_token(user_id, user["email"])
        response.set_cookie(key="access_token", value=new_access, httponly=True, secure=False, samesite="lax", max_age=3600, path="/")
        return {"message": "Token refreshed"}
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

@app.post("/api/auth/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    email = req.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user:
        return {"message": "If the email exists, a reset link has been sent."}
    token = secrets.token_urlsafe(32)
    await db.password_reset_tokens.insert_one({
        "token": token,
        "user_id": str(user["_id"]),
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "used": False
    })
    logger.info(f"Password reset token for {email}: {token}")
    return {"message": "If the email exists, a reset link has been sent."}

@app.post("/api/auth/reset-password")
async def reset_password(req: ResetPasswordRequest):
    record = await db.password_reset_tokens.find_one({"token": req.token, "used": False})
    if not record or record["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    await db.users.update_one(
        {"_id": ObjectId(record["user_id"])},
        {"$set": {"password_hash": hash_password(req.new_password)}}
    )
    await db.password_reset_tokens.update_one({"token": req.token}, {"$set": {"used": True}})
    return {"message": "Password reset successfully"}

# ─── URL Availability Check ──────────────────────────────────────────────────
@app.get("/api/check-url")
async def check_url_endpoint(url: str, user: dict = Depends(get_current_user)):
    """Quick availability check without saving. Returns {available, title, reason}."""
    if not validate_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL")
    result = await quick_availability_check(url)
    return result

# ─── Save Flow ────────────────────────────────────────────────────────────────
@app.post("/api/save")
async def save_url(req: SaveRequest, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    url = req.url.strip()
    if not validate_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL")

    platform = detect_platform(url)
    if not platform:
        raise HTTPException(status_code=400, detail="Unsupported platform. Only Instagram Reels, YouTube Shorts, and Facebook Reels are supported.")

    # Quick availability pre-check — fail fast before creating a DB record.
    # We only reject on DEFINITIVE signals (removed/private); timeouts pass through.
    check = await quick_availability_check(url)
    if not check["available"] and check.get("reason") != "timeout":
        raise HTTPException(
            status_code=422,
            detail={"type": "unavailable", "reason": check["reason"] or "Content not found or no longer accessible"}
        )

    # Check duplicate
    existing = await db.items.find_one({"url": url, "user_id": user["id"]})
    if existing:
        return {"item_id": str(existing["_id"]), "status": "duplicate", "message": "This URL has already been saved."}

    item_doc = {
        "user_id": user["id"],
        "url": url,
        "platform": platform,
        "title": "",
        "summary": "",
        "key_points": [],
        "steps": [],
        "ingredients": [],
        "transcript_excerpt": "",
        "visual_text": "",
        "category": "",
        "sub_category": "",
        "tags": [],
        "thumbnail_url": "",
        "source_status": "processing",
        "is_place_related": False,
        "confidence_score": 0.0,
        "notes": "",
        "retry_count": 0,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    result = await db.items.insert_one(item_doc)
    item_id = str(result.inserted_id)

    # Create processing job
    await db.processing_jobs.insert_one({
        "item_id": item_id,
        "status": "pending",
        "step_name": "metadata_extraction",
        "error_message": "",
        "started_at": datetime.now(timezone.utc),
        "completed_at": None
    })

    background_tasks.add_task(process_item, item_id, url, platform, user["id"])
    return {"item_id": item_id, "status": "processing"}

# ─── Category → Collection Auto-Assignment ───────────────────────────────────
CATEGORY_COLLECTION_MAP = {
    "Fitness & Health":      "Fitness & Health",
    "Sports":                "Fitness & Health",
    "Travel":                "Travel",
    "Nature & Outdoors":     "Travel",
    "Food & Recipes":        "Food & Recipes",
    "Technology":            "Technology",
    "Education & Learning":  "Learning",
    "DIY & Crafts":          "Learning",
    "Entertainment":         "Entertainment",
    "Comedy & Humor":        "Entertainment",
    "Music":                 "Entertainment",
    "Gaming":                "Entertainment",
    "Art & Creativity":      "Entertainment",
    "Finance & Money":       "Finance",
    "Career & Business":     "Finance",
    "Fashion & Beauty":      "Fashion & Style",
    "Skincare":              "Fashion & Style",
    "Shopping":              "Fashion & Style",
    "Parenting":             "Learning",
    "Motivation":            "Learning",
    "Relationships":         "Entertainment",
    "Pets & Animals":        "Entertainment",
}

async def auto_assign_to_collection(item_id: str, user_id: str, ai_result: dict):
    """Auto-assign an item to a matching collection based on its AI category."""
    try:
        category = ai_result.get("category", "")
        target_name = CATEGORY_COLLECTION_MAP.get(category)
        if not target_name:
            return
        # Find matching collection (case-insensitive)
        coll = await db.collections.find_one({
            "user_id": user_id,
            "name": {"$regex": f"^{re.escape(target_name)}$", "$options": "i"}
        })
        if not coll:
            return
        collection_id = str(coll["_id"])
        # Only insert if not already in the collection
        existing = await db.item_collection_map.find_one({
            "collection_id": collection_id,
            "item_id": item_id
        })
        if not existing:
            await db.item_collection_map.insert_one({
                "collection_id": collection_id,
                "item_id": item_id,
                "added_at": datetime.now(timezone.utc)
            })
            logger.info(f"Auto-assigned item {item_id} to collection '{target_name}'")
    except Exception:
        pass  # never crash the pipeline

# ─── Background Processing Pipeline ──────────────────────────────────────────
async def process_item(item_id: str, url: str, platform: str, user_id: str):
    try:
        logger.info(f"Processing item {item_id} ({platform}): {url}")

        # ── Step 1: Metadata extraction (yt-dlp for all platforms) ──────────
        await db.processing_jobs.update_one(
            {"item_id": item_id},
            {"$set": {"status": "running", "step_name": "metadata_extraction"}}
        )
        metadata = await extract_metadata(url, platform)
        logger.info(f"Metadata extracted for {item_id}: '{metadata.get('title', 'N/A')}'")

        # Update item with early metadata so UI shows thumbnail quickly
        await db.items.update_one({"_id": ObjectId(item_id)}, {"$set": {
            "title": metadata.get("title", ""),
            "thumbnail_url": metadata.get("thumbnail_url", ""),
            "updated_at": datetime.now(timezone.utc)
        }})

        # Guard: if extraction yielded nothing at all, treat as unavailable rather
        # than letting the AI hallucinate content from thin air.
        if (not metadata.get("title") and not metadata.get("description")
                and not metadata.get("thumbnail_url")):
            raise ContentUnavailableError(
                f"No content could be extracted from {url} — post may be deleted, private, or login-gated"
            )

        # ── Step 2: Vision analysis — send thumbnail frames to GPT-4o ───────
        visual_text = ""
        thumb_urls = metadata.get("thumbnail_urls", [])
        if not thumb_urls and metadata.get("thumbnail_url"):
            thumb_urls = [metadata["thumbnail_url"]]

        if thumb_urls:
            try:
                await db.processing_jobs.update_one(
                    {"item_id": item_id},
                    {"$set": {"step_name": "vision_analysis"}}
                )
                from services.ai_service import analyze_thumbnails_with_vision
                visual_text = await analyze_thumbnails_with_vision(thumb_urls)
                if visual_text:
                    metadata["visual_text"] = visual_text
                    logger.info(f"Vision analysis done for {item_id}: {len(visual_text)} chars")
            except Exception as e:
                logger.warning(f"Vision analysis skipped for {item_id}: {e}")

        # ── Step 3: Audio transcript — works for YouTube, Instagram, Facebook ─
        transcript = ""
        try:
            from services.extraction import extract_transcript_from_video
            await db.processing_jobs.update_one(
                {"item_id": item_id},
                {"$set": {"step_name": "transcript_extraction"}}
            )
            transcript = await extract_transcript_from_video(url, platform)
            if transcript:
                metadata["transcript"] = transcript
                logger.info(f"Transcript extracted for {item_id}: {len(transcript)} chars")
        except Exception as e:
            logger.warning(f"Transcript extraction skipped for {item_id}: {e}")

        # ── Step 4: AI categorization with full context ──────────────────────
        await db.processing_jobs.update_one(
            {"item_id": item_id},
            {"$set": {"step_name": "ai_categorization"}}
        )
        ai_result = await asyncio.wait_for(categorize_content(metadata), timeout=60)
        logger.info(f"AI done for {item_id}: category={ai_result.get('category')}, "
                    f"key_points={len(ai_result.get('key_points', []))}, "
                    f"steps={len(ai_result.get('steps', []))}")

        # ── Update item with all AI + enrichment results ─────────────────────
        ai_update = {
            "title": ai_result.get("title") or metadata.get("title", "Untitled"),
            "summary": ai_result.get("summary", ""),
            "key_points": ai_result.get("key_points", []),
            "steps": ai_result.get("steps", []),
            "ingredients": ai_result.get("ingredients", []),
            "transcript_excerpt": ai_result.get("transcript_excerpt", ""),
            "visual_text": visual_text[:500] if visual_text else "",
            "category": ai_result.get("category", "Other"),
            "sub_category": ai_result.get("sub_category", ""),
            "tags": ai_result.get("tags", []),
            "is_place_related": ai_result.get("is_place_related", False),
            "confidence_score": ai_result.get("confidence_score", 0.5),
            "source_status": "completed",
            "updated_at": datetime.now(timezone.utc)
        }
        await db.items.update_one({"_id": ObjectId(item_id)}, {"$set": ai_update})

        # Step 3: Geocoding for place-related items
        if ai_result.get("is_place_related") and ai_result.get("places"):
            await db.processing_jobs.update_one(
                {"item_id": item_id},
                {"$set": {"step_name": "geocoding"}}
            )
            for place_entry in ai_result["places"][:5]:
                # AI returns "Venue Name, City, Country" — use first part as display name
                display_name = place_entry.split(",")[0].strip() if "," in place_entry else place_entry
                coords = await geocode_place(place_entry)
                if coords:
                    await db.places.insert_one({
                        "item_id": item_id,
                        "name": display_name,
                        "address": coords.get("address", ""),
                        "latitude": coords["lat"],
                        "longitude": coords["lon"],
                        "geocode_source": "nominatim",
                        "created_at": datetime.now(timezone.utc)
                    })

        # ── Step 5: Auto-assign to matching collection ───────────────────────
        await auto_assign_to_collection(item_id, user_id, ai_result)

        # Complete processing
        await db.processing_jobs.update_one(
            {"item_id": item_id},
            {"$set": {"status": "completed", "step_name": "done", "completed_at": datetime.now(timezone.utc)}}
        )
        logger.info(f"Processing complete for item {item_id}")

    except ContentUnavailableError as e:
        logger.warning(f"Content unavailable for {item_id}: {e}")
        await db.items.update_one(
            {"_id": ObjectId(item_id)},
            {"$set": {"source_status": "unavailable", "updated_at": datetime.now(timezone.utc)}}
        )
        await db.processing_jobs.update_one(
            {"item_id": item_id},
            {"$set": {"status": "unavailable", "error_message": str(e), "completed_at": datetime.now(timezone.utc)}}
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.error(f"Processing failed for {item_id}: {str(e)}")
        await db.items.update_one(
            {"_id": ObjectId(item_id)},
            {"$set": {"source_status": "failed", "updated_at": datetime.now(timezone.utc)}}
        )
        await db.processing_jobs.update_one(
            {"item_id": item_id},
            {"$set": {"status": "failed", "error_message": str(e), "completed_at": datetime.now(timezone.utc)}}
        )

# ─── Items Routes ─────────────────────────────────────────────────────────────
@app.get("/api/items")
async def list_items(
    user: dict = Depends(get_current_user),
    category: Optional[str] = None,
    platform: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    query = {"user_id": user["id"]}
    if category:
        query["category"] = category
    if platform:
        query["platform"] = platform
    if status:
        query["source_status"] = status

    total = await db.items.count_documents(query)
    skip = (page - 1) * limit
    cursor = db.items.find(query).sort("created_at", -1).skip(skip).limit(limit)
    items = []
    async for doc in cursor:
        items.append(serialize_doc(doc))

    return {"items": items, "total": total, "page": page, "limit": limit, "pages": (total + limit - 1) // limit}

@app.get("/api/items/{item_id}")
async def get_item(item_id: str, user: dict = Depends(get_current_user)):
    item = await db.items.find_one({"_id": ObjectId(item_id), "user_id": user["id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item_data = serialize_doc(item)

    # Get places
    places = []
    async for place in db.places.find({"item_id": item_id}):
        places.append(serialize_doc(place))
    item_data["places"] = places

    # Get collections
    collections = []
    async for mapping in db.item_collection_map.find({"item_id": item_id}):
        coll = await db.collections.find_one({"_id": ObjectId(mapping["collection_id"])})
        if coll:
            collections.append(serialize_doc(coll))
    item_data["collections"] = collections

    # Get processing status
    job = await db.processing_jobs.find_one({"item_id": item_id})
    if job:
        item_data["processing"] = serialize_doc(job)

    return item_data

@app.put("/api/items/{item_id}")
async def update_item(item_id: str, req: UpdateItemRequest, user: dict = Depends(get_current_user)):
    item = await db.items.find_one({"_id": ObjectId(item_id), "user_id": user["id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    update_fields = {"updated_at": datetime.now(timezone.utc)}
    if req.title is not None:       update_fields["title"] = req.title
    if req.summary is not None:     update_fields["summary"] = req.summary
    if req.category is not None:    update_fields["category"] = req.category
    if req.sub_category is not None: update_fields["sub_category"] = req.sub_category
    if req.tags is not None:        update_fields["tags"] = req.tags
    if req.notes is not None:       update_fields["notes"] = req.notes
    if req.key_points is not None:  update_fields["key_points"] = req.key_points
    if req.steps is not None:       update_fields["steps"] = req.steps
    if req.ingredients is not None: update_fields["ingredients"] = req.ingredients

    await db.items.update_one({"_id": ObjectId(item_id)}, {"$set": update_fields})
    updated = await db.items.find_one({"_id": ObjectId(item_id)})
    return serialize_doc(updated)

@app.delete("/api/items/{item_id}")
async def delete_item(item_id: str, user: dict = Depends(get_current_user)):
    item = await db.items.find_one({"_id": ObjectId(item_id), "user_id": user["id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    await db.items.delete_one({"_id": ObjectId(item_id)})
    await db.places.delete_many({"item_id": item_id})
    await db.item_collection_map.delete_many({"item_id": item_id})
    await db.processing_jobs.delete_many({"item_id": item_id})
    return {"message": "Item deleted"}

# ─── Collections Routes ──────────────────────────────────────────────────────
@app.post("/api/collections")
async def create_collection(req: CreateCollectionRequest, user: dict = Depends(get_current_user)):
    coll_doc = {
        "user_id": user["id"],
        "name": req.name,
        "description": req.description or "",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    result = await db.collections.insert_one(coll_doc)
    coll_doc["_id"] = result.inserted_id
    return serialize_doc(coll_doc)

@app.get("/api/collections")
async def list_collections(user: dict = Depends(get_current_user)):
    collections = []
    async for coll in db.collections.find({"user_id": user["id"]}).sort("created_at", -1):
        coll_data = serialize_doc(coll)
        count = await db.item_collection_map.count_documents({"collection_id": coll_data["id"]})
        coll_data["item_count"] = count
        collections.append(coll_data)
    return {"collections": collections}

@app.get("/api/collections/{collection_id}")
async def get_collection(collection_id: str, user: dict = Depends(get_current_user)):
    coll = await db.collections.find_one({"_id": ObjectId(collection_id), "user_id": user["id"]})
    if not coll:
        raise HTTPException(status_code=404, detail="Collection not found")
    coll_data = serialize_doc(coll)

    # Get items in collection
    items = []
    async for mapping in db.item_collection_map.find({"collection_id": collection_id}):
        item = await db.items.find_one({"_id": ObjectId(mapping["item_id"])})
        if item:
            items.append(serialize_doc(item))
    coll_data["items"] = items
    coll_data["item_count"] = len(items)
    return coll_data

@app.put("/api/collections/{collection_id}")
async def update_collection(collection_id: str, req: CreateCollectionRequest, user: dict = Depends(get_current_user)):
    coll = await db.collections.find_one({"_id": ObjectId(collection_id), "user_id": user["id"]})
    if not coll:
        raise HTTPException(status_code=404, detail="Collection not found")
    await db.collections.update_one(
        {"_id": ObjectId(collection_id)},
        {"$set": {"name": req.name, "description": req.description or "", "updated_at": datetime.now(timezone.utc)}}
    )
    updated = await db.collections.find_one({"_id": ObjectId(collection_id)})
    return serialize_doc(updated)

@app.delete("/api/collections/{collection_id}")
async def delete_collection(collection_id: str, user: dict = Depends(get_current_user)):
    coll = await db.collections.find_one({"_id": ObjectId(collection_id), "user_id": user["id"]})
    if not coll:
        raise HTTPException(status_code=404, detail="Collection not found")
    await db.collections.delete_one({"_id": ObjectId(collection_id)})
    await db.item_collection_map.delete_many({"collection_id": collection_id})
    return {"message": "Collection deleted"}

@app.get("/api/collections/{collection_id}/available-items")
async def get_available_items(collection_id: str, user: dict = Depends(get_current_user)):
    """Return all items not yet in this collection, for the manual picker."""
    coll = await db.collections.find_one({"_id": ObjectId(collection_id), "user_id": user["id"]})
    if not coll:
        raise HTTPException(status_code=404, detail="Collection not found")
    # IDs already in the collection
    in_coll = set()
    async for mapping in db.item_collection_map.find({"collection_id": collection_id}):
        in_coll.add(mapping["item_id"])
    items = []
    async for doc in db.items.find({"user_id": user["id"], "source_status": "completed"}).sort("created_at", -1).limit(200):
        serialized = serialize_doc(doc)
        serialized["in_collection"] = serialized["id"] in in_coll
        items.append(serialized)
    return {"items": items, "collection_name": coll["name"]}

@app.post("/api/collections/{collection_id}/items")
async def add_item_to_collection(collection_id: str, req: AddItemToCollectionRequest, user: dict = Depends(get_current_user)):
    coll = await db.collections.find_one({"_id": ObjectId(collection_id), "user_id": user["id"]})
    if not coll:
        raise HTTPException(status_code=404, detail="Collection not found")
    item = await db.items.find_one({"_id": ObjectId(req.item_id), "user_id": user["id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    existing = await db.item_collection_map.find_one({"collection_id": collection_id, "item_id": req.item_id})
    if existing:
        return {"message": "Item already in collection"}

    await db.item_collection_map.insert_one({
        "collection_id": collection_id,
        "item_id": req.item_id,
        "added_at": datetime.now(timezone.utc)
    })
    return {"message": "Item added to collection"}

@app.delete("/api/collections/{collection_id}/items/{item_id}")
async def remove_item_from_collection(collection_id: str, item_id: str, user: dict = Depends(get_current_user)):
    coll = await db.collections.find_one({"_id": ObjectId(collection_id), "user_id": user["id"]})
    if not coll:
        raise HTTPException(status_code=404, detail="Collection not found")
    await db.item_collection_map.delete_one({"collection_id": collection_id, "item_id": item_id})
    return {"message": "Item removed from collection"}

# ─── Search Routes ────────────────────────────────────────────────────────────
@app.get("/api/search")
async def search_items(
    q: str = "",
    category: Optional[str] = None,
    platform: Optional[str] = None,
    collection_id: Optional[str] = None,
    tag: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user)
):
    query = {"user_id": user["id"]}

    if q:
        query["$text"] = {"$search": q}

    if category:
        query["category"] = {"$regex": category, "$options": "i"}
    if platform:
        query["platform"] = platform
    if tag:
        query["tags"] = {"$in": [tag]}

    # If filtering by collection
    if collection_id:
        item_ids = []
        async for mapping in db.item_collection_map.find({"collection_id": collection_id}):
            item_ids.append(ObjectId(mapping["item_id"]))
        query["_id"] = {"$in": item_ids}

    total = await db.items.count_documents(query)
    skip = (page - 1) * limit

    if q:
        cursor = db.items.find(query, {"score": {"$meta": "textScore"}}).sort([("score", {"$meta": "textScore"})]).skip(skip).limit(limit)
    else:
        cursor = db.items.find(query).sort("created_at", -1).skip(skip).limit(limit)

    items = []
    async for doc in cursor:
        doc.pop("score", None)
        items.append(serialize_doc(doc))

    return {"items": items, "total": total, "page": page, "query": q}

# ─── Map Routes ───────────────────────────────────────────────────────────────
@app.get("/api/map")
async def get_map_items(
    user: dict = Depends(get_current_user),
    category: Optional[str] = None
):
    # Get all items that are place-related
    item_query = {"user_id": user["id"], "is_place_related": True}
    if category:
        item_query["category"] = category

    map_items = []
    async for item in db.items.find(item_query):
        item_data = serialize_doc(item)
        places = []
        async for place in db.places.find({"item_id": item_data["id"]}):
            places.append(serialize_doc(place))
        if places:
            item_data["places"] = places
            map_items.append(item_data)

    return {"items": map_items}

# ─── Categories Route ─────────────────────────────────────────────────────────
@app.get("/api/categories")
async def get_categories(user: dict = Depends(get_current_user)):
    pipeline = [
        {"$match": {"user_id": user["id"], "category": {"$ne": ""}}},
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    categories = []
    async for doc in db.items.aggregate(pipeline):
        categories.append({"name": doc["_id"], "count": doc["count"]})
    return {"categories": categories}

# ─── Retry Processing ─────────────────────────────────────────────────────────
@app.post("/api/items/{item_id}/retry")
async def retry_processing(item_id: str, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    item = await db.items.find_one({"_id": ObjectId(item_id), "user_id": user["id"]})
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    retry_count = item.get("retry_count", 0)
    if retry_count >= MAX_RETRIES:
        raise HTTPException(status_code=400, detail=f"Maximum retries ({MAX_RETRIES}) reached for this item.")

    current_status = item.get("source_status")

    # Allow retry for: failed, completed, unavailable.
    # Also allow retrying a stuck "processing" item (>10 min old) as a safety valve.
    stuck = False
    if current_status == "processing":
        updated_at = item.get("updated_at")
        if updated_at and (datetime.now(timezone.utc) - updated_at).total_seconds() > 600:
            stuck = True
        else:
            raise HTTPException(status_code=400, detail="Item is already being processed")

    if current_status not in ["failed", "completed", "unavailable"] and not stuck:
        raise HTTPException(status_code=400, detail="Item is already being processed")

    await db.items.update_one(
        {"_id": ObjectId(item_id)},
        {"$set": {"source_status": "processing"}, "$inc": {"retry_count": 1}}
    )
    await db.processing_jobs.update_one(
        {"item_id": item_id},
        {"$set": {"status": "pending", "step_name": "metadata_extraction", "error_message": "", "started_at": datetime.now(timezone.utc), "completed_at": None}},
        upsert=True
    )
    background_tasks.add_task(process_item, item_id, item["url"], item["platform"], user["id"])
    return {"message": "Processing restarted", "retry_count": retry_count + 1, "retries_remaining": MAX_RETRIES - retry_count - 1}
