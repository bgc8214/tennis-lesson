"use client";

import { useState } from "react";
import { updateReaction } from "@/lib/api";
import type { ReactionValue } from "@/types/lesson";

interface ReactionButtonsProps {
  lessonId: string;
  targetKey: string;
  initialValue?: ReactionValue | null;
  className?: string;
}

/**
 * 13문서 대체카드: 셀프 음성 메모(강등)를 대체하는 최저마찰 입력.
 * 카드/타임스탬프 단위로 도움됐는지 여부만 탭 — 낙관적 업데이트, 실패 시 되돌림.
 */
export function ReactionButtons({
  lessonId,
  targetKey,
  initialValue,
  className,
}: ReactionButtonsProps) {
  const [value, setValue] = useState<ReactionValue | null>(initialValue ?? null);
  const [pending, setPending] = useState(false);

  const handleClick = async (next: ReactionValue) => {
    if (pending) return;
    const prev = value;
    const nextValue = prev === next ? null : next;
    setValue(nextValue);
    setPending(true);
    try {
      await updateReaction(lessonId, targetKey, nextValue);
    } catch {
      setValue(prev);
    } finally {
      setPending(false);
    }
  };

  return (
    <div
      className={["flex items-center gap-1", className].filter(Boolean).join(" ")}
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        onClick={() => handleClick("up")}
        aria-label="이 피드백 도움됐어요"
        aria-pressed={value === "up"}
        disabled={pending}
        className={[
          "inline-flex h-6 w-6 items-center justify-center rounded-full text-sm leading-none transition-colors",
          value === "up" ? "bg-brand-100" : "hover:bg-gray-100",
        ].join(" ")}
      >
        👍
      </button>
      <button
        type="button"
        onClick={() => handleClick("down")}
        aria-label="이 피드백 도움 안 됐어요"
        aria-pressed={value === "down"}
        disabled={pending}
        className={[
          "inline-flex h-6 w-6 items-center justify-center rounded-full text-sm leading-none transition-colors",
          value === "down" ? "bg-gray-200" : "hover:bg-gray-100",
        ].join(" ")}
      >
        👎
      </button>
    </div>
  );
}
