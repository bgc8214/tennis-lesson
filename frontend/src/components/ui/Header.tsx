"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getSupabaseClient } from "@/lib/supabase";
import type { User } from "@supabase/supabase-js";

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden>
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
    </svg>
  );
}

export function Header() {
  const [user, setUser] = useState<User | null>(null);
  const [credits, setCredits] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const supabase = getSupabaseClient();
    supabase.auth.getSession().then(({ data }) => {
      setUser(data.session?.user ?? null);
      setLoading(false);
    });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_e, session) => {
      setUser(session?.user ?? null);
    });
    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!user) { setCredits(null); return; }
    const supabase = getSupabaseClient();
    supabase.from("user_credits").select("credits").eq("user_id", user.id).single()
      .then(({ data }) => { if (data) setCredits(data.credits); });
  }, [user]);

  const handleGoogleLogin = async () => {
    const supabase = getSupabaseClient();
    await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/`,
      },
    });
  };

  const handleLogout = async () => {
    const supabase = getSupabaseClient();
    await supabase.auth.signOut();
    setUser(null);
    setCredits(null);
  };

  return (
    <header className="sticky top-0 z-40 border-b border-gray-100 bg-white/85 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:h-16 sm:px-6">
        <Link href="/" className="group flex items-center gap-2 font-bold tracking-tight">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500 text-white shadow-sm transition group-hover:bg-brand-600" aria-hidden>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5">
              <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2Zm0 18a8 8 0 0 1-7.43-5h2.06a6 6 0 0 0 10.74 0h2.06A8 8 0 0 1 12 20Zm-7.43-9a8 8 0 0 1 14.86 0h-2.06a6 6 0 0 0-10.74 0Z" />
            </svg>
          </span>
          <span className="text-base sm:text-lg">오늘의 테니스</span>
        </Link>

        <div className="flex items-center gap-3">
          {!loading && (
            user ? (
              <>
                {credits !== null && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5" aria-hidden>
                      <path d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm.75-11.25a.75.75 0 0 0-1.5 0v2.5h-2.5a.75.75 0 0 0 0 1.5h2.5v2.5a.75.75 0 0 0 1.5 0v-2.5h2.5a.75.75 0 0 0 0-1.5h-2.5v-2.5Z" />
                    </svg>
                    {credits}회 남음
                  </span>
                )}
                <span className="hidden text-xs text-gray-500 sm:block">
                  {user.email?.split("@")[0]}
                </span>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
                >
                  로그아웃
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={handleGoogleLogin}
                className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50"
              >
                <GoogleIcon />
                Google로 로그인
              </button>
            )
          )}
        </div>
      </div>
    </header>
  );
}
