import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

export const configurationError =
  !supabaseUrl || !publishableKey
    ? "The teacher application is not configured. Add the two public Supabase browser variables."
    : null;

export const supabase = configurationError
  ? null
  : createClient(supabaseUrl, publishableKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    });
