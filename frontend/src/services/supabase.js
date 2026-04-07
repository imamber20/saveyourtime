import { createClient } from '@supabase/supabase-js';

const SUPABASE_URL     = process.env.REACT_APP_SUPABASE_URL     || 'https://placeholder.supabase.co';
const SUPABASE_ANON_KEY = process.env.REACT_APP_SUPABASE_ANON_KEY || 'placeholder-anon-key';

// Singleton Supabase client — used only for Realtime subscriptions.
// All data fetching still goes through the FastAPI backend.
export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    // We manage auth ourselves (custom JWTs via HTTP-only cookies).
    // Disable Supabase Auth auto-refresh so it doesn't interfere.
    persistSession: false,
    autoRefreshToken: false,
    detectSessionInUrl: false,
  },
  realtime: {
    params: {
      eventsPerSecond: 5,
    },
  },
});
