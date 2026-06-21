"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getSupabaseClient } from "@/lib/supabase";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { useToast } from "@/components/ui/Toast";

type Mode = "magic" | "password-signin" | "password-signup";

export default function AuthPage() {
  const router = useRouter();
  const toast = useToast();
  const [mode, setMode] = useState<Mode>("magic");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [magicSent, setMagicSent] = useState(false);

  // 이미 로그인된 경우 대시보드로
  useEffect(() => {
    const supabase = getSupabaseClient();
    supabase.auth.getSession().then(({ data }) => {
      if (data.session) router.replace("/");
    });
  }, [router]);

  const siteUrl =
    process.env.NEXT_PUBLIC_SITE_URL ??
    (typeof window !== "undefined" ? window.location.origin : "");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting) return;
    const supabase = getSupabaseClient();
    setIsSubmitting(true);

    try {
      if (mode === "magic") {
        const { error } = await supabase.auth.signInWithOtp({
          email: email.trim(),
          options: {
            emailRedirectTo: `${siteUrl}/auth`,
          },
        });
        if (error) throw error;
        setMagicSent(true);
        toast.show("이메일로 매직 링크를 보냈습니다.", "success");
      } else if (mode === "password-signin") {
        const { error } = await supabase.auth.signInWithPassword({
          email: email.trim(),
          password,
        });
        if (error) throw error;
        toast.show("로그인 되었습니다.", "success");
        router.replace("/");
        router.refresh();
      } else {
        const { error } = await supabase.auth.signUp({
          email: email.trim(),
          password,
          options: {
            emailRedirectTo: `${siteUrl}/auth`,
          },
        });
        if (error) throw error;
        toast.show(
          "가입 메일을 확인해 주세요. 인증 후 다시 로그인할 수 있어요.",
          "success",
        );
      }
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "처리 중 오류가 발생했습니다.";
      toast.show(msg, "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-md py-8 sm:py-16">
      <div className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="mb-6 text-center">
          <h1 className="text-xl font-extrabold text-gray-900 sm:text-2xl">
            오늘의 테니스에 오신 것을 환영해요
          </h1>
          <p className="mt-2 text-sm text-gray-600">
            이메일로 간편하게 시작하세요
          </p>
        </div>

        {/* 모드 토글 */}
        <div className="mb-5 flex rounded-xl bg-gray-100 p-1 text-xs sm:text-sm">
          {(
            [
              ["magic", "매직 링크"],
              ["password-signin", "비밀번호 로그인"],
              ["password-signup", "회원가입"],
            ] as const
          ).map(([m, label]) => (
            <button
              key={m}
              type="button"
              onClick={() => {
                setMode(m);
                setMagicSent(false);
              }}
              className={`flex-1 rounded-lg px-2 py-1.5 font-medium transition ${
                mode === m
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {magicSent && mode === "magic" ? (
          <div className="rounded-xl border border-brand-200 bg-brand-50 p-4 text-sm text-brand-800">
            <strong className="font-semibold">{email}</strong> 으로 매직 링크를
            보냈습니다. 메일함을 확인해 주세요.
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label
                htmlFor="email"
                className="mb-1 block text-xs font-semibold text-gray-700"
              >
                이메일
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full rounded-xl border-2 border-gray-200 px-4 py-3 text-sm focus:border-brand-500 focus:outline-none"
              />
            </div>

            {mode !== "magic" && (
              <div>
                <label
                  htmlFor="password"
                  className="mb-1 block text-xs font-semibold text-gray-700"
                >
                  비밀번호
                </label>
                <input
                  id="password"
                  type="password"
                  autoComplete={
                    mode === "password-signup"
                      ? "new-password"
                      : "current-password"
                  }
                  required
                  minLength={6}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full rounded-xl border-2 border-gray-200 px-4 py-3 text-sm focus:border-brand-500 focus:outline-none"
                />
              </div>
            )}

            <button
              type="submit"
              disabled={isSubmitting}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-500 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-600 disabled:opacity-60"
            >
              {isSubmitting ? (
                <LoadingSpinner size="sm" />
              ) : mode === "magic" ? (
                "매직 링크 받기"
              ) : mode === "password-signin" ? (
                "로그인"
              ) : (
                "가입하기"
              )}
            </button>
          </form>
        )}

        <p className="mt-6 text-center text-xs text-gray-400">
          <Link href="/" className="hover:text-gray-600">
            ← 홈으로
          </Link>
        </p>
      </div>
    </div>
  );
}
