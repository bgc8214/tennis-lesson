-- ============================================================
-- Phase 2: Court Tactics 마이그레이션
-- 대상 프로젝트: bjcfxhodpucnoynpbdfm
-- 실행 순서: Phase 1 lesson_reports 테이블 존재 후 실행
-- ============================================================

-- 1) court_tactics JSONB 컬럼 추가
--    기본값 NULL (Phase 1에서 생성된 기존 레코드는 NULL 유지)
ALTER TABLE lesson_reports
  ADD COLUMN IF NOT EXISTS court_tactics JSONB DEFAULT NULL;

-- 2) court_analysis_status 상태 추적 컬럼
--    NULL = 미실행, PROCESSING = 분석중, DONE = 완료, FAILED = 실패
ALTER TABLE lesson_reports
  ADD COLUMN IF NOT EXISTS court_analysis_status TEXT DEFAULT NULL;

-- 3) JSONB 배열 인덱스 (court_tactics가 존재하는 행만 필터링할 때 유용)
CREATE INDEX IF NOT EXISTS idx_lesson_reports_court_tactics_exists
  ON lesson_reports ((court_tactics IS NOT NULL))
  WHERE court_tactics IS NOT NULL;

-- 4) court_analysis_status 인덱스 (PROCESSING 상태 조회 등)
CREATE INDEX IF NOT EXISTS idx_lesson_reports_court_analysis_status
  ON lesson_reports (court_analysis_status)
  WHERE court_analysis_status IS NOT NULL;

-- 5) JSONB 유효성 체크 제약조건
--    court_tactics가 NULL이 아니면 반드시 JSON 배열이어야 함
ALTER TABLE lesson_reports
  ADD CONSTRAINT chk_court_tactics_is_array
  CHECK (
    court_tactics IS NULL
    OR jsonb_typeof(court_tactics) = 'array'
  );

-- ============================================================
-- 참고: court_tactics 배열 항목 스키마 (애플리케이션 레벨 검증)
-- {
--   "sec": integer (>= 0),
--   "position": string (enum: net_left, net_center, net_right,
--                        service_line_left, service_line_center, service_line_right,
--                        baseline_left, baseline_center, baseline_right, unknown),
--   "position_x": float (0.0 ~ 1.0),
--   "position_y": float (0.0 ~ 1.0),
--   "category": string,
--   "tactic": string,
--   "label": string,
--   "quote": string | null
-- }
-- ============================================================

-- 6) RLS 정책은 기존 lesson_reports에 이미 적용되어 있으므로 추가 불필요.
--    기존 정책:
--      SELECT: auth.uid() = (SELECT user_id FROM lessons WHERE id = lesson_reports.lesson_id)
--      INSERT/UPDATE/DELETE: service_role 전용 (백엔드에서만 수행)
--    court_tactics 컬럼도 동일한 RLS 정책으로 보호됨.
