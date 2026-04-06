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

from services.extraction import validate_url, detect_platform, extract_metadata
from services.ai_service import categorize_content
from services.geocoding import geocode_place

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
        await db.users.insert_one({
            "email": ADMIN_EMAIL,
            "password_hash": hash_password(ADMIN_PASSWORD),
            "name": "Admin",
            "role": "admin",
            "created_at": datetime.now(timezone.utc)
        })
        logger.info(f"Admin user seeded: {ADMIN_EMAIL}")
    elif not verify_password(ADMIN_PASSWORD, existing["password_hash"]):
        await db.users.update_one({"email": ADMIN_EMAIL}, {"$set": {"password_hash": hash_password(ADMIN_PASSWORD)}})

    # Write test credentials
    os.makedirs("/app/memory", exist_ok=True)
    with open("/app/memory/test_credentials.md", "w") as f:
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
@app.post("/api/auth/register")
async def register(req: RegisterRequest, response: Response):
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

# ─── Save Flow ────────────────────────────────────────────────────────────────
@app.post("/api/save")
async def save_url(req: SaveRequest, background_tasks: BackgroundTasks, user: dict = Depends(get_current_user)):
    url = req.url.strip()
    if not validate_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL")

    platform = detect_platform(url)
    if not platform:
        raise HTTPException(status_code=400, detail="Unsupported platform. Only Instagram Reels, YouTube Shorts, and Facebook Reels are supported.")

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
        "category": "",
        "sub_category": "",
        "tags": [],
        "thumbnail_url": "",
        "source_status": "processing",
        "is_place_related": False,
        "confidence_score": 0.0,
        "notes": "",
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

# ─── Background Processing Pipeline ──────────────────────────────────────────
async def process_item(item_id: str, url: str, platform: str, user_id: str):
    try:
        logger.info(f"Processing item {item_id}: {url}")

        # Step 1: Metadata extraction
        await db.processing_jobs.update_one(
            {"item_id": item_id},
            {"$set": {"status": "running", "step_name": "metadata_extraction"}}
        )
        metadata = await extract_metadata(url, platform)
        logger.info(f"Metadata extracted for {item_id}: {metadata.get('title', 'N/A')}")

        # Update item with raw metadata
        update_fields = {
            "title": metadata.get("title", ""),
            "thumbnail_url": metadata.get("thumbnail_url", ""),
            "updated_at": datetime.now(timezone.utc)
        }
        await db.items.update_one({"_id": ObjectId(item_id)}, {"$set": update_fields})

        # Step 1.5: Attempt transcript extraction for YouTube (enriches AI input)
        if platform == "youtube":
            try:
                from services.extraction import extract_transcript_from_video
                await db.processing_jobs.update_one(
                    {"item_id": item_id},
                    {"$set": {"step_name": "transcript_extraction"}}
                )
                transcript = await extract_transcript_from_video(url, platform)
                if transcript:
                    metadata["transcript"] = transcript
                    logger.info(f"Transcript added for {item_id}")
            except Exception as e:
                logger.warning(f"Transcript extraction skipped for {item_id}: {e}")

        # Step 2: AI categorization
        await db.processing_jobs.update_one(
            {"item_id": item_id},
            {"$set": {"step_name": "ai_categorization"}}
        )
        ai_result = await categorize_content(metadata)
        logger.info(f"AI categorization for {item_id}: {ai_result.get('category', 'N/A')}")

        # Update item with AI results
        ai_update = {
            "title": ai_result.get("title") or metadata.get("title", "Untitled"),
            "summary": ai_result.get("summary", ""),
            "category": ai_result.get("category", "Uncategorized"),
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
            for place_name in ai_result["places"][:5]:
                coords = await geocode_place(place_name)
                if coords:
                    await db.places.insert_one({
                        "item_id": item_id,
                        "name": place_name,
                        "address": coords.get("address", ""),
                        "latitude": coords["lat"],
                        "longitude": coords["lon"],
                        "geocode_source": "nominatim",
                        "created_at": datetime.now(timezone.utc)
                    })

        # Complete processing
        await db.processing_jobs.update_one(
            {"item_id": item_id},
            {"$set": {"status": "completed", "step_name": "done", "completed_at": datetime.now(timezone.utc)}}
        )
        logger.info(f"Processing complete for item {item_id}")

    except Exception as e:
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
    if req.title is not None:
        update_fields["title"] = req.title
    if req.summary is not None:
        update_fields["summary"] = req.summary
    if req.category is not None:
        update_fields["category"] = req.category
    if req.sub_category is not None:
        update_fields["sub_category"] = req.sub_category
    if req.tags is not None:
        update_fields["tags"] = req.tags
    if req.notes is not None:
        update_fields["notes"] = req.notes

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
    if item.get("source_status") not in ["failed", "completed"]:
        raise HTTPException(status_code=400, detail="Item is already being processed")

    await db.items.update_one({"_id": ObjectId(item_id)}, {"$set": {"source_status": "processing"}})
    await db.processing_jobs.update_one(
        {"item_id": item_id},
        {"$set": {"status": "pending", "step_name": "metadata_extraction", "error_message": "", "started_at": datetime.now(timezone.utc), "completed_at": None}},
        upsert=True
    )
    background_tasks.add_task(process_item, item_id, item["url"], item["platform"], user["id"])
    return {"message": "Processing restarted"}
