-- 15문서 2-A: transcript_quality + stt_stats/verification 영속화
-- Supabase 프로젝트 bjcfxhodpucnoynpbdfm에 2026-07-19 적용 완료(mcp__supabase__apply_migration).
-- 이 파일은 기록용 — 재실행 시 IF NOT EXISTS로 안전.

ALTER TABLE lesson_reports
  ADD COLUMN IF NOT EXISTS transcript_quality text
    CHECK (transcript_quality IS NULL OR transcript_quality IN ('high', 'low')),
  ADD COLUMN IF NOT EXISTS stt_stats jsonb,
  ADD COLUMN IF NOT EXISTS verification jsonb;

COMMENT ON COLUMN lesson_reports.transcript_quality IS
  '15문서 2-A: 인용(quote) 노출 여부 판단용 등급. 판정 로직 부재 확인됨(match_score/필터
   통과율이 실제 품질과 상관 없음, 골든셋 검토 3건 실증) — whisper 경로는 현재 항상
   low로 고정. 향후 진짜 판정 신호가 발견되면 그때 갱신.';
COMMENT ON COLUMN lesson_reports.stt_stats IS
  '15문서 2-A: STT 필터 통계(stt_providers.transcribe_audio 반환값) 영속화 — 향후
   품질 판정 로직 실험을 위한 원시 데이터 축적 목적.';
COMMENT ON COLUMN lesson_reports.verification IS
  '15문서 2-A: 인용 검증 게이트 통계(verification.verify_report 반환값) 영속화 — 동일 목적.';
