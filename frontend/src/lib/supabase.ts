"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

let cachedClient: SupabaseClient | null = null;

/**
 * 브라우저 환경 Supabase 클라이언트 (싱글턴).
 * - anon key 사용. RLS 정책에 의해 본인 row 만 SELECT/DELETE 가능.
 * - 세션 토큰은 localStorage 가 아닌 쿠키 기반으로 관리되어 SSR 과 공유.
 */
export function getSupabaseClient(): SupabaseClient {
  if (cachedClient) return cachedClient;

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !anonKey) {
    throw new Error(
      "Supabase 환경변수가 설정되지 않았습니다. NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY 를 확인하세요.",
    );
  }

  cachedClient = createBrowserClient(url, anonKey);
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
