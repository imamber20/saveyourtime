#!/usr/bin/env python3
"""
MongoDB → Supabase Migration Script
=====================================
Migrates all data from the local MongoDB instance to the Supabase project.

Run from the project root:
    python scripts/migrate_mongo_to_supabase.py [--dry-run]

Requirements:
    pip install pymongo supabase python-dotenv

Environment variables (loaded from backend/.env):
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
    MONGO_URL  (default: mongodb://localhost:27017)
    DB_NAME    (default: content_memory)
"""

import os
import sys
import uuid
import asyncio
import argparse
import logging
from datetime import datetime, timezone
from typing import Optional

# ─── Path setup ───────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_DIR  = os.path.join(PROJECT_ROOT, "backend")

# Load backend env
from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

SUPABASE_URL              = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
MONGO_URL                 = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME                   = os.environ.get("DB_NAME", "content_memory")

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("migrate")


def mongo_id_to_uuid(oid_str: str) -> str:
    """Convert a MongoDB ObjectId hex string to a deterministic UUID v5."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, oid_str))


def parse_dt(val) -> Optional[str]:
    """Convert a MongoDB datetime (or None) to an ISO string."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.isoformat()
    if isinstance(val, str):
        return val
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Main migration ───────────────────────────────────────────────────────────
async def run_migration(dry_run: bool):
    from pymongo import MongoClient
    from supabase import acreate_client

    log.info(f"Connecting to MongoDB: {MONGO_URL}/{DB_NAME}")
    mongo   = MongoClient(MONGO_URL)
    mdb     = mongo[DB_NAME]

    log.info("Connecting to Supabase…")
    sb = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    # ── 1. Users ──────────────────────────────────────────────────────────────
    log.info("=== Migrating users ===")
    # Map: old MongoDB ObjectId string → new Supabase Auth UUID
    user_id_map: dict = {}

    for u in mdb.users.find():
        old_id    = str(u["_id"])
        email     = u.get("email", "").lower().strip()
        name      = u.get("name", "User")
        role      = u.get("role", "user")
        password  = u.get("password_hash", "")  # hashed, unusable directly

        if not email:
            log.warning(f"Skipping user {old_id}: no email")
            continue

        # Check if user already exists in Supabase Auth
        existing_id = None
        try:
            all_users = await sb.auth.admin.list_users()
            for au in all_users:
                if au.email == email:
                    existing_id = au.id
                    break
        except Exception:
            pass

        if existing_id:
            log.info(f"  User {email} already in Supabase (id={existing_id})")
            user_id_map[old_id] = existing_id
        elif dry_run:
            fake_id = mongo_id_to_uuid(old_id)
            log.info(f"  [DRY-RUN] Would create user {email} → {fake_id}")
            user_id_map[old_id] = fake_id
        else:
            # Create user in Supabase Auth with a temporary password
            # Users will need to reset their password after migration
            temp_password = f"Migrated_{old_id[-6:]}!Tmp"
            try:
                res = await sb.auth.admin.create_user({
                    "email": email,
                    "password": temp_password,
                    "email_confirm": True,
                    "user_metadata": {"name": name, "role": role,
                                      "migrated_from_mongo": old_id},
                })
                new_id = res.user.id
                user_id_map[old_id] = new_id
                # Update profile role for admins
                if role == "admin":
                    await sb.table("profiles").update({"role": "admin", "name": name}) \
                        .eq("id", new_id).execute()
                log.info(f"  Created user {email} → {new_id}  (temp pw: {temp_password})")
            except Exception as e:
                log.error(f"  Failed to create user {email}: {e}")
                user_id_map[old_id] = mongo_id_to_uuid(old_id)  # fallback

    log.info(f"  User map: {len(user_id_map)} entries")

    # ── 2. Items ──────────────────────────────────────────────────────────────
    log.info("=== Migrating items ===")
    item_id_map: dict = {}

    for doc in mdb.items.find():
        old_id   = str(doc["_id"])
        new_id   = mongo_id_to_uuid(old_id)
        user_oid = str(doc.get("user_id", ""))
        user_id  = user_id_map.get(user_oid)

        if not user_id:
            log.warning(f"  Skipping item {old_id}: user {user_oid} not found in map")
            continue

        item_doc = {
            "id":                 new_id,
            "user_id":            user_id,
            "url":                doc.get("url", ""),
            "platform":           doc.get("platform", "youtube"),
            "title":              doc.get("title", ""),
            "summary":            doc.get("summary", ""),
            "author":             doc.get("author", ""),
            "duration":           doc.get("duration", ""),
            "key_points":         doc.get("key_points", []),
            "steps":              doc.get("steps", []),
            "ingredients":        doc.get("ingredients", []),
            "transcript_excerpt": doc.get("transcript_excerpt", ""),
            "visual_text":        doc.get("visual_text", ""),
            "category":           doc.get("category", ""),
            "sub_category":       doc.get("sub_category", ""),
            "tags":               doc.get("tags", []),
            "thumbnail_url":      doc.get("thumbnail_url", ""),
            "source_status":      doc.get("source_status", "completed"),
            "is_place_related":   doc.get("is_place_related", False),
            "is_public":          doc.get("is_public", False),
            "confidence_score":   float(doc.get("confidence_score", 0.5)),
            "notes":              doc.get("notes", ""),
            "retry_count":        int(doc.get("retry_count", 0)),
            "hype_count":         int(doc.get("hype_count", 0)),
            "created_at":         parse_dt(doc.get("created_at")) or now_iso(),
            "updated_at":         parse_dt(doc.get("updated_at")) or now_iso(),
        }

        item_id_map[old_id] = new_id

        if dry_run:
            log.info(f"  [DRY-RUN] Would insert item {old_id} → {new_id}  '{doc.get('title','')[:40]}'")
            continue

        try:
            # Check if item already exists (idempotent)
            existing = await sb.table("items").select("id").eq("id", new_id).maybe_single().execute()
            if existing.data:
                log.info(f"  Item {new_id} already exists, skipping")
            else:
                await sb.table("items").insert(item_doc).execute()
                log.info(f"  Inserted item '{doc.get('title','')[:40]}' → {new_id}")
        except Exception as e:
            log.error(f"  Failed item {old_id}: {e}")

    # ── 3. Collections ────────────────────────────────────────────────────────
    log.info("=== Migrating collections ===")
    coll_id_map: dict = {}

    for doc in mdb.collections.find():
        old_id  = str(doc["_id"])
        new_id  = mongo_id_to_uuid(old_id)
        user_oid = str(doc.get("user_id", ""))
        user_id  = user_id_map.get(user_oid)

        if not user_id:
            log.warning(f"  Skipping collection {old_id}: user not found")
            continue

        coll_doc = {
            "id":          new_id,
            "user_id":     user_id,
            "name":        doc.get("name", ""),
            "description": doc.get("description", ""),
            "created_at":  parse_dt(doc.get("created_at")) or now_iso(),
            "updated_at":  parse_dt(doc.get("updated_at")) or now_iso(),
        }
        coll_id_map[old_id] = new_id

        if dry_run:
            log.info(f"  [DRY-RUN] Would insert collection '{doc.get('name','')}' → {new_id}")
            continue

        try:
            existing = await sb.table("collections").select("id").eq("id", new_id).maybe_single().execute()
            if existing.data:
                log.info(f"  Collection {new_id} already exists, skipping")
            else:
                await sb.table("collections").insert(coll_doc).execute()
                log.info(f"  Inserted collection '{doc.get('name','')}' → {new_id}")
        except Exception as e:
            log.error(f"  Failed collection {old_id}: {e}")

    # ── 4. Item-Collection Map ────────────────────────────────────────────────
    log.info("=== Migrating item-collection mappings ===")
    for doc in mdb.item_collection_map.find():
        old_coll_id = str(doc.get("collection_id", ""))
        old_item_id = str(doc.get("item_id", ""))
        new_coll_id = coll_id_map.get(old_coll_id)
        new_item_id = item_id_map.get(old_item_id)

        if not new_coll_id or not new_item_id:
            log.warning(f"  Skipping mapping {old_coll_id}→{old_item_id}: IDs not found")
            continue

        if dry_run:
            log.info(f"  [DRY-RUN] Would insert mapping {new_coll_id} ← {new_item_id}")
            continue

        try:
            existing = await sb.table("item_collection_map").select("id") \
                .eq("collection_id", new_coll_id).eq("item_id", new_item_id).maybe_single().execute()
            if not existing.data:
                await sb.table("item_collection_map").insert({
                    "collection_id": new_coll_id,
                    "item_id":       new_item_id,
                    "added_at":      parse_dt(doc.get("added_at")) or now_iso(),
                }).execute()
        except Exception as e:
            log.error(f"  Failed mapping: {e}")

    # ── 5. Places ─────────────────────────────────────────────────────────────
    log.info("=== Migrating places ===")
    for doc in mdb.places.find():
        old_item_id = str(doc.get("item_id", ""))
        new_item_id = item_id_map.get(old_item_id)

        if not new_item_id:
            log.warning(f"  Skipping place: item {old_item_id} not found")
            continue

        place_doc = {
            "item_id":       new_item_id,
            "name":          doc.get("name", ""),
            "address":       doc.get("address", ""),
            "latitude":      doc.get("latitude"),
            "longitude":     doc.get("longitude"),
            "geocode_source": doc.get("geocode_source", "nominatim"),
            "created_at":    parse_dt(doc.get("created_at")) or now_iso(),
        }

        if dry_run:
            log.info(f"  [DRY-RUN] Would insert place '{doc.get('name','')}' for item {new_item_id}")
            continue

        try:
            await sb.table("places").insert(place_doc).execute()
        except Exception as e:
            log.error(f"  Failed place '{doc.get('name','')}': {e}")

    # ── 6. Processing Jobs ────────────────────────────────────────────────────
    log.info("=== Migrating processing jobs ===")
    for doc in mdb.processing_jobs.find():
        old_item_id = str(doc.get("item_id", ""))
        new_item_id = item_id_map.get(old_item_id)

        if not new_item_id:
            continue

        job_doc = {
            "item_id":       new_item_id,
            "status":        doc.get("status", "completed"),
            "step_name":     doc.get("step_name", "done"),
            "error_message": doc.get("error_message", ""),
            "started_at":    parse_dt(doc.get("started_at")) or now_iso(),
            "completed_at":  parse_dt(doc.get("completed_at")),
        }

        if dry_run:
            log.info(f"  [DRY-RUN] Would insert job for item {new_item_id}")
            continue

        try:
            existing = await sb.table("processing_jobs").select("id") \
                .eq("item_id", new_item_id).maybe_single().execute()
            if not existing.data:
                await sb.table("processing_jobs").insert(job_doc).execute()
        except Exception as e:
            log.error(f"  Failed job for item {new_item_id}: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    log.info("")
    log.info("╔══════════════════════════════════╗")
    if dry_run:
        log.info("║  DRY-RUN complete — no changes   ║")
    else:
        log.info("║  Migration complete!              ║")
    log.info("╚══════════════════════════════════╝")
    log.info(f"  Users migrated:       {len(user_id_map)}")
    log.info(f"  Items migrated:       {len(item_id_map)}")
    log.info(f"  Collections migrated: {len(coll_id_map)}")
    if not dry_run:
        log.info("")
        log.info("⚠️  Users have TEMPORARY passwords of the form: Migrated_<6chars>!Tmp")
        log.info("    They will need to use 'Forgot Password' to set a new password.")

    mongo.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate MongoDB → Supabase")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be migrated without writing anything")
    args = parser.parse_args()

    if "PASTE_SERVICE_ROLE_KEY_HERE" in os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""):
        print("❌  SUPABASE_SERVICE_ROLE_KEY is not set in backend/.env")
        print("    Get it from: Supabase Dashboard → Project Settings → API → service_role (secret)")
        sys.exit(1)

    asyncio.run(run_migration(dry_run=args.dry_run))
