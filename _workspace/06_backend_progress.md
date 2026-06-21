# 06. 백엔드 - 분석 진행 상태 실시간 노출

> 사용자가 2~3분 대기하는 동안 현재 어떤 단계에 있는지 알 수 있도록,
> 분석 파이프라인이 진행될 때마다 DB에 진행 메시지를 갱신한다.

## 핵심 결정

- **새 컬럼 추가하지 않는다.** `lesson_reports.error_message` 컬럼을
  `processing_status = PROCESSING` 동안에만 "진행 메시지" 용도로 재활용.
- DONE 시점에는 `error_message = NULL`로 덮어쓰고(기존 코드 유지),
  FAILED 시점에는 본래 의도대로 에러 메시지를 기록한다.
- API 응답에서는 상태에 따라 두 키로 분리해 노출:
  - `progress_message` ← `error_message` (status == PROCESSING)
  - `error_message`    ← `error_message` (status == FAILED)
  - 그 외 상태에서는 둘 다 `null`.

## 진행 메시지 단계 (3-step)

| 단계 | 트리거 시점 | 메시지 |
| --- | --- | --- |
| 1/3 | `_run_analysis_pipeline` PROCESSING 전이 직후 | `🎵 오디오 다운로드 중... (1/3)` |
| 2/3 | `gemini_service`에서 오디오 다운로드 + 청크 분할 완료 직후 | `🔍 영상 분석 중... (2/3) — N개 구간 병렬 처리` |
| 3/3 | 모든 청크 분석 완료, 최종 합산/정리 직전 | `📝 오답노트 정리 중... (3/3)` |
| 완료 | DONE 저장 시 | `error_message = null` (기존 동작) |
| 실패 | FAILED 저장 시 | `Gemini 분석 실패: ...` (기존 동작) |

## 변경 파일

### 1) `backend/app/routers/lessons.py`

- `_update_progress(sb, lesson_id, message, now_fn)` 헬퍼 추가.
  - `lesson_reports.error_message`와 `updated_at`만 업데이트.
  - 진행 메시지 갱신 실패는 무시(파이프라인 본 흐름을 깨지 않기 위함).
- `_run_analysis_pipeline()` 내부:
  - PROCESSING 전이 직후 1단계 메시지 기록.
  - `gemini_service.generate_lesson_report(...)` 호출 시
    `progress_callback=lambda msg: _update_progress(sb, lesson_id, msg, now)` 전달.
- `_serialize_report()` 시그니처 변화:
  - `progress_message` 필드 신설.
  - `error_message`는 `status == "FAILED"`일 때만 노출,
    `progress_message`는 `status == "PROCESSING"`일 때만 노출.

### 2) `backend/app/services/gemini_service.py`

- `from typing` 임포트에 `Callable` 추가.
- `generate_lesson_report(youtube_url, progress_callback=None)` 시그니처 확장.
  - 콜백은 선택적이며, 호출 시 예외는 무시(`_notify` 내부 try/except).
- 단계 알림 위치:
  - 청크 분할 완료 직후: `🔍 영상 분석 중... (2/3) — N개 구간 병렬 처리`
    (실제 청크 수를 동적으로 삽입)
  - 청크 분석 전부 완료 후 합산 직전: `📝 오답노트 정리 중... (3/3)`
- 오디오 다운로드(1/3) 메시지는 라우터 측에서 PROCESSING 진입 직후 기록하므로
  서비스 내부에서 별도 알림하지 않는다.

## API 응답 변화

```jsonc
// PROCESSING 중
{
  "data": {
    ...,
    "processing_status": "PROCESSING",
    "report": null   // 기존대로 null (PROCESSING/PENDING이면 report 미반환)
  }
}
```

> 주의: 현재 `get_lesson` 엔드포인트는 `processing_status in ("DONE", "FAILED")`
> 일 때만 `report`를 채워 보낸다. 따라서 `progress_message`를 프런트로 노출하려면
> 다음 중 하나의 추가 결정이 필요하다.
>
> 1. **(권장)** `get_lesson`에서 PROCESSING 상태에도 부분 리포트(`progress_message`만 채움)를
>    내려주도록 분기 보강.
> 2. 별도의 `/lessons/{id}/status` 폴링 엔드포인트 신설.
>
> 본 단계에서는 직렬화 경로(`_serialize_report`)와 DB 기록까지만 마쳤다.
> `get_lesson` 분기 변경은 프런트 폴링 정책과 함께 다음 작업으로 분리한다.

## 회귀 위험 요약

- `error_message` 컬럼을 임시 재활용하므로, 외부 도구가 이 컬럼을 직접 읽고 있다면
  PROCESSING 동안 에러로 오해할 가능성 있음. 내부 사용만 있으므로 영향 없음.
- 콜백 실패는 모두 swallow → 분석 파이프라인 자체 안정성에는 영향 없음.
- 프런트는 `progress_message` 키 신설 외 추가 변경 없음.
