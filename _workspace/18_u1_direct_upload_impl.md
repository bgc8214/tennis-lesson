# 18. U-1 직접 업로드 MVP 구현 완료 (2026-07-20)

17문서 U-1(유튜브 링크 없이 영상 파일 직접 업로드해 분석) MVP 구현. U-0 실측
(폰 6.3GB/3.8초 추출, WORKERFS 스트리밍) 통과 후 착수. 오케스트레이터가 직접 구현.

## 데이터 흐름
```
[브라우저]
  영상 File 선택 → FFmpeg.wasm(WORKERFS) demux → 오디오 Uint8Array
  → SHA-256(오디오만) → multipart POST /lessons/analyze-upload (오디오만 전송)
[백엔드]
  오디오 임시 저장(스트리밍) → source_type='upload' 레슨 생성 → 202
  → 백그라운드: whisper 파이프라인(STT→PassA→검증→PassB) → DONE → 임시파일 삭제
[리포트 화면]
  source_type='upload' → LocalVideoPlayer (사용자가 기기에서 영상 재선택해 로컬 재생)
  텍스트/타임라인은 영상 없이도 완전 열람 가능
```

## DB 마이그레이션 (적용 완료 — Supabase project bjcfxhodpucnoynpbdfm)
migration `add_upload_source_type`:
- `lessons.source_type text not null default 'youtube'` (check: youtube|upload)
- `lessons.file_hash text null`
- `lessons.youtube_url` → nullable로 완화
- 롤백 필요 시: 세 변경 역순 + check 제약/컬럼 drop

## 백엔드 변경 파일
- `app/models/lesson.py`
  - `SourceType` 리터럴 추가
  - `LessonAnalyzeUploadResponse`(youtube_video_id 없음) 추가
  - `LessonSummary`: youtube_url Optional화 + source_type/file_hash 추가
- `app/services/gemini_service.py` (순수 리팩터링 + 신규 진입점)
  - `_generate_report_from_audio_path(audio_path, on_progress)` — STT~PassB 공통 본체 추출
  - `generate_lesson_report_whisper` — yt-dlp 다운로드 후 위 공통 호출로 축소 (동작 불변)
  - `generate_lesson_report_whisper_from_upload(audio_path, on_progress)` — 다운로드 없이 공통 호출
- `app/routers/lessons.py`
  - `_ensure_credits` 헬퍼로 크레딧 체크 추출 (analyze/analyze-upload 공유)
  - `_serialize_lesson_summary` + list/get select에 source_type/file_hash 반영
  - `_run_upload_analysis_pipeline` — 업로드 전용 백그라운드(whisper만, court 없음, 임시파일 정리)
  - `POST /lessons/analyze-upload` (multipart: audio/duration_sec/file_hash/title?)
    - 크레딧 체크 → duration 가드(YTDLP_MAX_DURATION_SEC 재사용) → file_hash 중복 체크
    - 오디오 스트리밍 저장(4MB 청크, 500MB 상한) → 레슨 insert → 202

## 프론트 변경 파일
- `src/lib/extractAudio.ts` (신규) — FFmpeg WORKERFS 추출 공용화 + sha256Hex + probeVideoDuration
- `src/app/dev/u0-ffmpeg-test/page.tsx` — 공용 함수 사용하도록 리팩터링(중복 제거)
- `src/types/lesson.ts` — SourceType, Upload 요청/응답 타입, LessonSummary nullable/신규 필드
- `src/lib/api.ts` — analyzeLessonUpload(multipart), rowToSummary + 양 select에 신규 컬럼
- `src/components/UrlInputForm.tsx` — [유튜브 링크|영상 파일] 탭, 업로드 상태머신(추출→업로드→접수)
- `src/components/ReportView/LocalVideoPlayer.tsx` (신규) — 로컬 파일 재생 + requestedSec seek
- `src/components/ReportView/index.tsx` — source_type 분기
- `src/components/LessonCard.tsx` — 업로드 레슨 플레이스홀더 + "📁 업로드" 뱃지

## 검증 완료
- 백엔드: `python -c "import main"` 앱 로드 OK, /lessons/analyze-upload 라우트 등록 확인
- 프론트: `tsc --noEmit` 통과, `next build` 성공

## 계약 (프론트/백엔드 일치 확인됨)
```
POST /api/v1/lessons/analyze-upload   multipart/form-data (Authorization)
  audio(file), duration_sec(int), file_hash(str), title?(str)
  → 202 { "data": { lesson_id, processing_status:"PENDING", created_at } }
  409 LESSON_ALREADY_EXISTS(file_hash 중복) / 413 FILE_TOO_LARGE / 422 VIDEO_TOO_LONG
```
- file_hash = **추출된 오디오**의 SHA-256 (원본 영상 해시 금지 — 메모리 재발 위험)

## 남은 것 (이번 스코프 밖)
- 실제 파일로 엔드투엔드 도그푸딩(게이트: 내 레슨 영상 유튜브 없이 분석 완료) — 서버 기동 후 수동
- 진행률 UX 정교화, 파일 해시 중복 안내 문구, 촬영 가이드 통합 → U-2
- 공유 클립(U-2.5), 영상 업로드 비전 트랙(U-3)
```
