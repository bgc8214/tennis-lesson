-- ============================================================
-- 05_lesson_type_migration.sql
-- 목적: lessons 테이블에 lesson_type(레슨 카테고리) 컬럼 추가
-- 적용일: 2026-06-04
--
-- 변경 사항
--   1) lessons 테이블에 TEXT[] 타입의 lesson_type 컬럼 추가
--      - 복합 레슨(예: "포핸드 + 백핸드")의 경우를 위해 배열로 설계
--      - 기본값은 빈 배열 '{}'
--   2) GIN 인덱스 추가
--      - `WHERE lesson_type @> ARRAY['포핸드']` / `&&` / `=` 검색 최적화
--      - Supabase python client의 .contains("lesson_type", [...]) 와 동일
--
-- 가능한 카테고리(애플리케이션 레벨에서 검증):
--   포핸드, 백핸드, 발리, 서브, 로브, 스텝, 풋워크, 게임레슨, 드롭샷, 어프로치
-- ============================================================

ALTER TABLE lessons
  ADD COLUMN IF NOT EXISTS lesson_type TEXT[] DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_lessons_lesson_type
  ON lessons USING GIN (lesson_type);

-- (선택) 기존 row의 NULL 값을 빈 배열로 백필
UPDATE lessons
   SET lesson_type = '{}'
 WHERE lesson_type IS NULL;
