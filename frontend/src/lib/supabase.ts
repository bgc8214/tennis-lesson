"use client";

import { createClient } from "@supabase/supabase-js";
import type { SupabaseClient } from "@supabase/supabase-js";

let cachedClient: SupabaseClient | null = null;

export function getSupabaseClient(): SupabaseClient {
  if (cachedClient) return cachedClient;

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !anonKey) {
    throw new Error(
      "Supabase 환경변수가 설정되지 않았습니다. NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY 를 확인하세요.",
    );
  }

  // localStorage 기반 세션 — OAuth 콜백 후 세션이 안정적으로 유지됨
  cachedClient = createClient(url, anonKey, {
    auth: {
      persistSession: true,
      storageKey: "sb-bjcfxhodpucnoynpbdfm-auth-token",
      storage: typeof window !== "undefined" ? window.localStorage : undefined,
      detectSessionInUrl: true,
      flowType: "pkce",
    },
  });
  return cachedClient;
}

/** 현재 세션의 access token 을 가져온다. 없으면 null. */
export async function getAccessToken(): Promise<string | null> {
  const supabase = getSupabaseClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}
