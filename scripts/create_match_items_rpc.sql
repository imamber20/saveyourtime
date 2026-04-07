-- Run this in the Supabase SQL Editor to enable vector search for global chat.
-- Requires the pgvector extension (already enabled via initial schema migration).

-- Ensure the embedding column exists with the right type
ALTER TABLE public.items
  ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- Create index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS items_embedding_idx
  ON public.items
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- RPC function called by library_chat() in chat_service.py
CREATE OR REPLACE FUNCTION match_items(
  query_embedding vector(1536),
  match_user_id   uuid,
  match_count     int DEFAULT 8
)
RETURNS TABLE (
  id               uuid,
  title            text,
  summary          text,
  category         text,
  sub_category     text,
  tags             jsonb,
  key_points       jsonb,
  platform         text,
  similarity       float
)
LANGUAGE sql STABLE
AS $$
  SELECT
    i.id,
    i.title,
    i.summary,
    i.category,
    i.sub_category,
    i.tags,
    i.key_points,
    i.platform,
    1 - (i.embedding <=> query_embedding) AS similarity
  FROM public.items i
  WHERE
    i.user_id       = match_user_id
    AND i.source_status = 'completed'
    AND i.embedding IS NOT NULL
  ORDER BY i.embedding <=> query_embedding
  LIMIT match_count;
$$;
