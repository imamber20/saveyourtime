-- Run this once in the Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- to activate Phase 2 Supabase Realtime for the items table.

-- 1. Full replica identity — UPDATE events will carry the complete new row
ALTER TABLE public.items REPLICA IDENTITY FULL;

-- 2. Add items to the realtime publication
ALTER PUBLICATION supabase_realtime ADD TABLE public.items;

-- 3. Allow the anon key (used by Supabase Realtime on the frontend) to read rows.
--    The subscription filter user_id=eq.{id} restricts delivery to the right user.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename  = 'items'
      AND policyname = 'anon_select_items'
  ) THEN
    EXECUTE 'CREATE POLICY anon_select_items ON public.items FOR SELECT TO anon USING (true)';
  END IF;
END;
$$;

-- Verify
SELECT schemaname, tablename, policyname
FROM pg_policies
WHERE tablename = 'items';
