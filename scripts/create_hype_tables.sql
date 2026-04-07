-- Run in the Supabase SQL Editor for Phase 5 (Hype & Trending)

-- 1. hypes junction table
CREATE TABLE IF NOT EXISTS public.hypes (
  item_id   uuid NOT NULL REFERENCES public.items(id) ON DELETE CASCADE,
  user_id   uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (item_id, user_id)
);

ALTER TABLE public.hypes ENABLE ROW LEVEL SECURITY;

-- Any authenticated user can hype/un-hype; anyone can read hypes
CREATE POLICY "users_manage_own_hypes" ON public.hypes
  FOR ALL TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "anon_read_hypes" ON public.hypes FOR SELECT TO anon USING (true);

-- 2. Add hype_count + is_public to items (if not already present)
ALTER TABLE public.items
  ADD COLUMN IF NOT EXISTS hype_count INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS is_public  BOOLEAN NOT NULL DEFAULT false;

-- 3. Trigger to increment / decrement hype_count and set is_public
CREATE OR REPLACE FUNCTION public.update_hype_count()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    UPDATE public.items
    SET hype_count = hype_count + 1,
        is_public  = true
    WHERE id = NEW.item_id;
  ELSIF TG_OP = 'DELETE' THEN
    UPDATE public.items
    SET hype_count = GREATEST(hype_count - 1, 0)
    WHERE id = OLD.item_id;
  END IF;
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS hype_counter ON public.hypes;
CREATE TRIGGER hype_counter
  AFTER INSERT OR DELETE ON public.hypes
  FOR EACH ROW EXECUTE FUNCTION public.update_hype_count();

-- 4. Indexes for trending page queries
CREATE INDEX IF NOT EXISTS items_hype_count_idx
  ON public.items (hype_count DESC) WHERE is_public = true;
CREATE INDEX IF NOT EXISTS items_is_public_created_idx
  ON public.items (created_at DESC) WHERE is_public = true;
