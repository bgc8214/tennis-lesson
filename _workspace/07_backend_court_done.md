# [07] Court Tactics Backend - 구현 완료

## 구현된 파일

### 신규 생성
| 파일 | 설명 |
|------|------|
| `backend/app/services/court_service.py` | 코트 전술 분석 파이프라인 메인 서비스 |
| `_workspace/07_migration_court_tactics.sql` | DB 마이그레이션 SQL (court_tactics, court_analysis_status 컬럼) |

### 수정됨
| 파일 | 변경 내용 |
|------|----------|
| `backend/app/config.py` | COURT_ANALYSIS_* 설정 6개 추가 (기본값 ENABLED=False) |
| `backend/app/models/report.py` | CourtPosition, CourtAnalysisStatus 타입 + CourtTactic 모델 + LessonReport 필드 추가 |
| `backend/app/routers/lessons.py` | _serialize_report에 court 필드, _run_analysis_pipeline에 court 호출, POST /{id}/court-analysis 엔드포인트 |
| `backend/requirements.txt` | ultralytics>=8.0, opencv-python-headless>=4.8 추가 |

---

## 엔드포인트

### POST /api/v1/lessons/{lesson_id}/court-analysis

별도로 코트 전술 분석을 트리거한다.

**조건:**
- `COURT_ANALYSIS_ENABLED=true` 환경변수 필요
- Phase 1 분석이 DONE 상태여야 함

**응답:**
- 202: 분석 시작됨
- 400: 레슨 미완료 (LESSON_NOT_READY)
- 404: 레슨 미존재/소유권 불일치
- 409: 이미 분석 중 (COURT_ANALYSIS_IN_PROGRESS)
- 422: 기능 비활성화 (FEATURE_DISABLED)

**curl 예시:**
```bash
curl -X POST http://localhost:8000/api/v1/lessons/{lesson_id}/court-analysis \
  -H "Authorization: Bearer <jwt>"
```

**202 응답:**
```json
{
  "data": {
    "lesson_id": "uuid",
    "court_analysis_status": "PROCESSING",
    "message": "코트 분석이 시작되었습니다."
  }
}
```

### GET /api/v1/lessons/{lesson_id} (확장)

기존 report 객체에 추가된 필드:
```json
{
  "court_tactics": [
    {
      "sec": 320,
      "position": "service_line_center",
      "position_x": 0.5,
      "position_y": 0.4,
      "category": "발리",
      "tactic": "네트에 더 붙어서 치기",
      "label": "발리 위치 교정",
      "quote": "거기서 치면 너무 멀어"
    }
  ],
  "court_analysis_status": "DONE"
}
```

---

## 파이프라인 흐름

```
1. POST /lessons/{id}/court-analysis (또는 Phase 1 DONE 시 자동)
2. lesson_reports.court_analysis_status = "PROCESSING"
3. timestamps에서 최대 10개 선택
4. 각 타임스탬프에 대해:
   a. yt-dlp로 +-20초 클립 다운로드 (480p)
   b. YOLOv8n(yolo11n.pt)으로 person 감지 (2fps 샘플링)
   c. bbox bottom-center -> 정규화 좌표 -> 9zone 스냅
   d. 실패 시 position="unknown" 폴백
5. 위치 + timestamps 데이터를 Gemini에 전달
6. Gemini가 전술 JSON 배열 반환
7. lesson_reports.court_tactics = 결과, status = "DONE"
```

---

## 설정 (환경변수)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `COURT_ANALYSIS_ENABLED` | `false` | 기능 플래그 (점진적 롤아웃) |
| `COURT_ANALYSIS_MAX_CLIPS` | `10` | 최대 분석 클립 수 |
| `COURT_ANALYSIS_CLIP_DURATION` | `40` | 클립 길이(초) |
| `COURT_ANALYSIS_VIDEO_HEIGHT` | `480` | 다운로드 해상도 |
| `COURT_ANALYSIS_YOLO_CONF` | `0.5` | YOLO 신뢰도 임계값 |
| `COURT_ANALYSIS_FPS_SAMPLE` | `2` | 초당 샘플링 프레임 수 |

---

## DB 마이그레이션

`_workspace/07_migration_court_tactics.sql` 실행 필요:
- `court_tactics JSONB DEFAULT NULL`
- `court_analysis_status TEXT DEFAULT NULL`
- 인덱스 2개 (존재 필터, 상태 필터)
- CHECK 제약조건 (배열 타입 검증)

---

## 에러 핸들링 전략

- 클립 다운로드 실패: 해당 클립 스킵, position="unknown"으로 Gemini에 전달
- YOLO 감지 실패: position="unknown" 폴백, Gemini가 quote에서 위치 추론
- Gemini 호출 실패: 기본 폴백 데이터 반환 (YOLO 결과 기반)
- 전체 실패: court_analysis_status="FAILED", Phase 1 리포트는 영향 없음
