#!/usr/bin/env python3
"""
MongoDB → Supabase Migration Script
=====================================
Migrates all data from the local MongoDB instance to the Supabase project.

Run from the project root:
    python scripts/migrate_mongo_to_supabase.py [--dry-run]

Requirements:
    pip install pymongo supabase python-dotenv
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

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_DIR, ".env"))

SUPABASE_URL              = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
MONGO_URL                 = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME                   = os.environ.get("DB_NAME", "content_memory")
ADMIN_EMAIL               = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower().strip()
ADMIN_PASSWORD            = os.environ.get("ADMIN_PASSWORD", "admin123")

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("migrate")


def mongo_id_to_uuid(oid_str: str) -> str:
    """Convert a MongoDB ObjectId hex string to a deterministic UUID v5."""
    return str(uuid.uuid5(uuid.NAMESPACE_OID, oid_str))


def parse_dt(val) -> Optional[str]:
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


def is_duplicate_error(e: Exception) -> bool:
    """Return True if the exception is a unique-constraint / duplicate key error."""
    msg = str(e).lower()
    return any(k in msg for k in ("duplicate", "unique", "23505", "already exists"))


async def row_exists(sb, table: str, **filters) -> bool:
    """Check if a row matching all filters exists — uses a list query (safe on all versions)."""
    q = sb.table(table).select("id")
    for col, val in filters.items():
        q = q.eq(col, val)
    res = await q.limit(1).execute()
    # In supabase-py 2.x, res.data is a list (possibly empty) — never None
    return bool(res and res.data)


# ─── Main migration ───────────────────────────────────────────────────────────
async def run_migration(dry_run: bool):
    from pymongo import MongoClient
    from supabase import acreate_client

    log.info(f"Connecting to MongoDB: {MONGO_URL}/{DB_NAME}")
    mongo = MongoClient(MONGO_URL)
    mdb   = mongo[DB_NAME]

    log.info("Connecting to Supabase…")
    sb = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    # ── 1. Users ──────────────────────────────────────────────────────────────
    log.info("=== Migrating users ===")
    user_id_map: dict = {}

    # Build lookup of existing Supabase Auth users
    try:
        existing_sb_users = {u.email: u.id for u in await sb.auth.admin.list_users()}
    except Exception:
        existing_sb_users = {}

    for u in mdb.users.find():
        old_id   = str(u["_id"])
        email    = u.get("email", "").lower().strip()
        name     = u.get("name", "User")
        role     = u.get("role", "user")

        if not email:
            log.warning(f"Skipping user {old_id}: no email")
            continue

        if email in existing_sb_users:
            new_id = existing_sb_users[email]
            log.info(f"  User {email} already in Supabase (id={new_id})")
            user_id_map[old_id] = new_id
            continue

        # Admin gets the real configured password; others get a temp password
        password = ADMIN_PASSWORD if email == ADMIN_EMAIL else f"Temp_{old_id[-8:]}!Reset"

        if dry_run:
            fake_id = mongo_id_to_uuid(old_id)
            log.info(f"  [DRY-RUN] Would create user {email} (role={role}) → {fake_id}")
            user_id_map[old_id] = fake_id
            continue

        try:
            res    = await sb.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"name": name, "role": role},
            })
            new_id = res.user.id
            user_id_map[old_id] = new_id
            if role == "admin":
                await sb.table("profiles").update({"role": "admin", "name": name}) \
                    .eq("id", new_id).execute()
                log.info(f"  Created ADMIN {email} → {new_id} (pw: {password})")
            else:
                log.info(f"  Created user {email} → {new_id} (temp pw: {password})")
        except Exception as e:
            log.error(f"  Failed to create user {email}: {e}")
            user_id_map[old_id] = mongo_id_to_uuid(old_id)

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
            log.warning(f"  Skipping item {old_id}: user {user_oid} not in map")
            continue

        item_id_map[old_id] = new_id

        if dry_run:
            log.info(f"  [DRY-RUN] {old_id} → {new_id}  '{doc.get('title','')[:50]}'")
            continue

        try:
            if await row_exists(sb, "items", id=new_id):
                log.info(f"  Item {new_id} already exists, skipping")
                continue

            await sb.table("items").insert({
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
                "is_place_related":   bool(doc.get("is_place_related", False)),
                "is_public":          bool(doc.get("is_public", False)),
                "confidence_score":   float(doc.get("confidence_score", 0.5)),
                "notes":              doc.get("notes", ""),
                "retry_count":        int(doc.get("retry_count", 0)),
                "hype_count":         int(doc.get("hype_count", 0)),
                "created_at":         parse_dt(doc.get("created_at")) or now_iso(),
                "updated_at":         parse_dt(doc.get("updated_at")) or now_iso(),
            }).execute()
            log.info(f"  ✓ Inserted '{doc.get('title','')[:50]}'")
        except Exception as e:
            if is_duplicate_error(e):
                log.info(f"  Item {new_id} already exists (duplicate), skipping")
            else:
                log.error(f"  ✗ Failed item {old_id}: {e}")

    # ── 3. Collections ────────────────────────────────────────────────────────
    log.info("=== Migrating collections ===")
    coll_id_map: dict = {}

    for doc in mdb.collections.find():
        old_id   = str(doc["_id"])
        new_id   = mongo_id_to_uuid(old_id)
        user_oid = str(doc.get("user_id", ""))
        user_id  = user_id_map.get(user_oid)

        if not user_id:
            log.warning(f"  Skipping collection {old_id}: user not in map")
            continue

        coll_id_map[old_id] = new_id

        if dry_run:
            log.info(f"  [DRY-RUN] '{doc.get('name','')}' → {new_id}")
            continue

        try:
            if await row_exists(sb, "collections", id=new_id):
                log.info(f"  Collection '{doc.get('name','')}' already exists, skipping")
                continue

            await sb.table("collections").insert({
                "id":          new_id,
                "user_id":     user_id,
                "name":        doc.get("name", ""),
                "description": doc.get("description", ""),
                "created_at":  parse_dt(doc.get("created_at")) or now_iso(),
                "updated_at":  parse_dt(doc.get("updated_at")) or now_iso(),
            }).execute()
            log.info(f"  ✓ Inserted collection '{doc.get('name','')}'")
        except Exception as e:
            if is_duplicate_error(e):
                log.info(f"  Collection already exists (duplicate), skipping")
            else:
                log.error(f"  ✗ Failed collection {old_id}: {e}")

    # ── 4. Item-Collection Mappings ───────────────────────────────────────────
    log.info("=== Migrating item-collection mappings ===")
    for doc in mdb.item_collection_map.find():
        old_coll = str(doc.get("collection_id", ""))
        old_item = str(doc.get("item_id", ""))
        new_coll = coll_id_map.get(old_coll)
        new_item = item_id_map.get(old_item)

        if not new_coll or not new_item:
            log.warning(f"  Skipping mapping {old_coll}→{old_item}: IDs not in map")
            continue

        if dry_run:
            log.info(f"  [DRY-RUN] mapping {new_coll[:8]}… ← {new_item[:8]}…")
            continue

        try:
            if await row_exists(sb, "item_collection_map", collection_id=new_coll, item_id=new_item):
                continue
            await sb.table("item_collection_map").insert({
                "collection_id": new_coll,
                "item_id":       new_item,
                "added_at":      parse_dt(doc.get("added_at")) or now_iso(),
            }).execute()
            log.info(f"  ✓ Mapping inserted")
        except Exception as e:
            if not is_duplicate_error(e):
                log.error(f"  ✗ Failed mapping: {e}")

    # ── 5. Places ─────────────────────────────────────────────────────────────
    log.info("=== Migrating places ===")
    for doc in mdb.places.find():
        old_item = str(doc.get("item_id", ""))
        new_item = item_id_map.get(old_item)

        if not new_item:
            log.warning(f"  Skipping place '{doc.get('name','')}': item {old_item} not in map")
            continue

        if dry_run:
            log.info(f"  [DRY-RUN] place '{doc.get('name','')}' for item {new_item[:8]}…")
            continue

        try:
            await sb.table("places").insert({
                "item_id":       new_item,
                "name":          doc.get("name", ""),
                "address":       doc.get("address", ""),
                "latitude":      doc.get("latitude"),
                "longitude":     doc.get("longitude"),
                "geocode_source": doc.get("geocode_source", "nominatim"),
                "created_at":    parse_dt(doc.get("created_at")) or now_iso(),
            }).execute()
            log.info(f"  ✓ Place '{doc.get('name','')}'")
        except Exception as e:
            log.error(f"  ✗ Failed place '{doc.get('name','')}': {e}")

    # ── 6. Processing Jobs ────────────────────────────────────────────────────
    log.info("=== Migrating processing jobs ===")
    for doc in mdb.processing_jobs.find():
        old_item = str(doc.get("item_id", ""))
        new_item = item_id_map.get(old_item)
        if not new_item:
            continue

        if dry_run:
            log.info(f"  [DRY-RUN] job for item {new_item[:8]}…")
            continue

        try:
            if await row_exists(sb, "processing_jobs", item_id=new_item):
                continue
            await sb.table("processing_jobs").insert({
                "item_id":       new_item,
                "status":        doc.get("status", "completed"),
                "step_name":     doc.get("step_name", "done"),
                "error_message": doc.get("error_message", ""),
                "started_at":    parse_dt(doc.get("started_at")) or now_iso(),
                "completed_at":  parse_dt(doc.get("completed_at")),
            }).execute()
        except Exception as e:
            if not is_duplicate_error(e):
                log.error(f"  ✗ Failed job: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    log.info("")
    log.info("╔══════════════════════════════════════╗")
    if dry_run:
        log.info("║  DRY-RUN complete — no changes made  ║")
    else:
        log.info("║  Migration complete! ✅               ║")
    log.info("╚══════════════════════════════════════╝")
    log.info(f"  Users:       {len(user_id_map)}")
    log.info(f"  Items:       {len(item_id_map)}")
    log.info(f"  Collections: {len(coll_id_map)}")

    mongo.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate MongoDB → Supabase")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing")
    args = parser.parse_args()

    if "PASTE_SERVICE_ROLE_KEY_HERE" in os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""):
        print("❌  SUPABASE_SERVICE_ROLE_KEY not set in backend/.env")
        sys.exit(1)

    asyncio.run(run_migration(dry_run=args.dry_run))
