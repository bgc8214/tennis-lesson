"use client";

import { useState } from "react";
import { updateQuickNote } from "@/lib/api";

interface QuickNoteProps {
  lessonId: string;
  initialValue?: string | null;
}

/**
 * 13문서 축3(셀프 음성 메모) 강등 후 저비용 수요 테스트.
 * 텍스트 한 줄도 안 쓰는 유저는 음성 녹음도 안 할 것이므로, 이 입력률이
 * 곧 셀프 메모 기능의 수요 신호다. 입력률이 유의미하면 음성으로 재승격 검토.
 */
export function QuickNote({ lessonId, initialValue }: QuickNoteProps) {
  const [value, setValue] = useState(initialValue ?? "");
  const [saved, setSaved] = useState(Boolean(initialValue));
  const [saving, setSaving] = useState(false);

  const handleBlur = async () => {
    const trimmed = value.trim();
    if (trimmed === (initialValue ?? "").trim()) return;
    setSaving(true);
    try {
      await updateQuickNote(lessonId, trimmed);
      setSaved(Boolean(trimmed));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm sm:p-5">
      <label htmlFor="quick-note" className="text-sm font-semibold text-gray-800">
        오늘 기억나는 지적이 있나요?{" "}
        <span className="font-normal text-gray-400">(선택)</span>
      </label>
      <textarea
        id="quick-note"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={handleBlur}
        maxLength={500}
        rows={2}
        placeholder="예: 왼손으로 공 잡는 거 계속 얘기하셨음"
        className="mt-2 w-full resize-none rounded-xl border border-gray-200 p-3 text-sm text-gray-800 outline-none focus:border-brand-400"
      />
      <p className="mt-1 text-right text-[11px] text-gray-400">
        {saving ? "저장 중..." : saved ? "저장됨" : ""}
      </p>
    </section>
  );
}
