"use client";

interface LessonTypeFilterProps {
  selected: string | null;
  onChange: (type: string | null) => void;
}

const LESSON_TYPES = [
  "포핸드",
  "백핸드",
  "발리",
  "서브",
  "로브",
  "스텝",
  "풋워크",
  "게임레슨",
  "드롭샷",
  "어프로치",
];

export function LessonTypeFilter({
  selected,
  onChange,
}: LessonTypeFilterProps) {
  return (
    <div className="flex flex-wrap gap-2">
      <button
        type="button"
        onClick={() => onChange(null)}
        className={`rounded-full px-3 py-1.5 text-sm font-medium transition ${
          selected === null
            ? "bg-green-500 text-white"
            : "bg-gray-100 text-gray-600 hover:bg-gray-200"
        }`}
      >
        전체
      </button>
      {LESSON_TYPES.map((type) => (
        <button
          key={type}
          type="button"
          onClick={() => onChange(selected === type ? null : type)}
          className={`rounded-full px-3 py-1.5 text-sm font-medium transition ${
            selected === type
              ? "bg-green-500 text-white"
              : "bg-gray-100 text-gray-600 hover:bg-gray-200"
          }`}
        >
          {type}
        </button>
      ))}
    </div>
  );
}
