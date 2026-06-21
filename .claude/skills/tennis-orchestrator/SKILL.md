---
name: tennis-orchestrator
description: "오늘의 테니스(Today's Tennis) 서비스 개발 에이전트 팀을 조율하는 오케스트레이터. 새 기능 구현, Phase별 개발 착수, 시스템 설계, 백엔드/프론트엔드/Vision AI 개발, 버그 수정, 코드 리뷰, 기능 추가 요청 시 반드시 이 스킬을 사용할 것. 후속 작업: 이전 결과 수정, 특정 Phase 재실행, 기능 업데이트, 아키텍처 변경, 코드 보완, 테스트 추가, '다시 해줘', '수정해줘', '추가해줘' 등 모든 개발 요청에 이 스킬을 사용."
---

# Tennis Orchestrator

오늘의 테니스 서비스 개발 에이전트 팀(architect, backend, frontend, vision, qa)을 조율하여 PMD 로드맵을 구현한다.

## 실행 모드: 하이브리드

| Phase | 모드 | 이유 |
|-------|------|------|
| Phase 1 (설계) | 서브 에이전트 (architect 단독) | 단일 전문가 작업, 팀 통신 불필요 |
| Phase 2 (개발) | 에이전트 팀 | backend·frontend·vision 간 실시간 협업 필요 |
| Phase 3 (QA) | 서브 에이전트 (qa 단독) | 독립적 검증, 팀 통신 불필요 |

## 에이전트 구성

| 에이전트 | 타입 | 역할 | 주요 스킬 |
|---------|------|------|---------|
| architect | 커스텀 | 시스템 설계 & DB 스키마 | 아키텍처 패턴 |
| backend | 커스텀 | FastAPI + AI 파이프라인 | youtube-ai-pipeline |
| frontend | 커스텀 | Next.js UI | lesson-report-builder |
| vision | 커스텀 | MediaPipe 관절 분석 | mediapipe-pose |
| qa | 커스텀 | 통합 검증 | 경계면 비교 |

## 워크플로우

### Phase 0: 컨텍스트 확인 (후속 작업 지원)

```
1. _workspace/ 디렉토리 존재 여부 확인
2. 실행 모드 결정:
   - _workspace/ 미존재 → 초기 실행, Phase 1 진행
   - _workspace/ 존재 + 부분 수정 요청 → 해당 에이전트만 재호출
     (예: "백엔드만 수정" → backend 에이전트만 재호출)
   - _workspace/ 존재 + 새 Phase/기능 → _workspace_YYYYMMDD_HHMMSS/로 이동 후 새 실행
3. 사용자 요청에서 대상 Phase 파악 (Phase 1 MVP / Phase 2 Vision AI / Phase 3 확장)
```

### Phase 1: 아키텍처 설계
**실행 모드:** 서브 에이전트

```
Agent(
  subagent_type: "architect",
  model: "opus",
  prompt: """
    오늘의 테니스 서비스의 [대상 Phase] 아키텍처를 설계하라.
    PMD를 읽고 다음을 산출하라:
    1. _workspace/01_architect_system-design.md — 전체 아키텍처 + 기술 결정 사항
    2. _workspace/01_architect_db-schema.sql — Supabase 테이블 DDL (RLS 포함)
    3. _workspace/01_architect_api-contracts.md — FastAPI 엔드포인트 명세 (OpenAPI 형식)
    
    Phase 1 제약: 인프라 비용 0원 (Gemini 무료 티어, YouTube 자막 API 우선)
    Phase 2 추가: MediaPipe 관절 데이터 DB 스키마 포함
    """
)
```

### Phase 2: 병렬 개발
**실행 모드:** 에이전트 팀

```
TeamCreate(
  team_name: "tennis-dev-team",
  members: [
    {
      name: "backend",
      agent_type: "backend",
      model: "opus",
      prompt: """
        architect의 API 계약(_workspace/01_architect_api-contracts.md)을 읽고
        youtube-ai-pipeline 스킬을 참조하여 FastAPI 백엔드를 구현하라.
        구현 완료된 엔드포인트마다 frontend에게 SendMessage로 알린다.
        최종 완료 시 qa에게 SendMessage로 "테스트 준비 완료" + 엔드포인트 목록 전송.
        산출: _workspace/02_backend_endpoints.md
        """
    },
    {
      name: "frontend",
      agent_type: "frontend",
      model: "opus",
      prompt: """
        PMD 7절 UI/UX 와이어프레임과 lesson-report-builder 스킬을 참조하여
        Next.js 프론트엔드를 구현하라.
        backend로부터 엔드포인트 알림을 기다리며, 준비된 것부터 순차 구현.
        완료 시 qa에게 SendMessage로 "프론트 완료" + 주요 페이지 경로 전송.
        산출: _workspace/03_frontend_pages.md
        """
    },
    {
      name: "vision",
      agent_type: "vision",
      model: "opus",
      prompt: """
        mediapipe-pose 스킬을 참조하여 Phase 2 관절 분석 모듈을 구현하라.
        (Phase 1 요청이면 이 에이전트는 대기 상태로 유지)
        아키텍처 DB 스키마 확인 후 출력 JSON 스키마를 확정하고
        backend에게 SendMessage로 "Vision 출력 스키마 확정" + 파일 경로 전송.
        산출: _workspace/02_vision_output-schema.json, _workspace/02_vision_metrics.md
        """
    }
  ]
)

TaskCreate(tasks: [
  { title: "FastAPI 기본 구조 세팅", assignee: "backend", description: "프로젝트 구조, 의존성, 환경변수" },
  { title: "YouTube 파싱 엔드포인트", assignee: "backend", description: "자막 + yt-dlp 폴백 파이프라인" },
  { title: "Gemini 오답노트 생성 엔드포인트", assignee: "backend", depends_on: ["YouTube 파싱 엔드포인트"] },
  { title: "Supabase 레슨 저장 API", assignee: "backend", depends_on: ["Gemini 오답노트 생성 엔드포인트"] },
  { title: "Next.js 프로젝트 초기 설정", assignee: "frontend" },
  { title: "메인 대시보드 페이지", assignee: "frontend", description: "URL 입력 폼 + 레슨 이력 그리드" },
  { title: "레슨 리포트 뷰 페이지", assignee: "frontend", description: "비디오 플레이어 + 3단 오답노트" },
  { title: "공유 버튼 컴포넌트", assignee: "frontend", depends_on: ["레슨 리포트 뷰 페이지"] },
  { title: "MediaPipe 파이프라인 구현", assignee: "vision" },
  { title: "3가지 스윙 메트릭 계산", assignee: "vision", depends_on: ["MediaPipe 파이프라인 구현"] },
  { title: "스켈레톤 오버레이 렌더링", assignee: "vision", depends_on: ["MediaPipe 파이프라인 구현"] },
])
```

팀 모니터링:
- 팀원들이 SendMessage로 서로 협업하며 자체 조율
- 리더는 TaskGet으로 진행 상황 확인
- 팀원이 유휴 상태가 되면 자동 알림 수신

### Phase 3: QA 검증
**실행 모드:** 서브 에이전트

```
TeamDelete("tennis-dev-team")  # 개발 팀 정리

Agent(
  subagent_type: "qa",
  model: "opus",
  prompt: """
    _workspace/의 모든 산출물과 실제 소스코드를 검증하라.
    
    필수 검증 항목:
    1. API 계약(_workspace/01_architect_api-contracts.md) vs 실제 구현 일치 여부
    2. 프론트엔드 컴포넌트가 소비하는 API 응답 shape 일치 여부
    3. Supabase RLS 정책 존재 여부
    4. 환경변수 하드코딩 없음 확인
    5. 핵심 사용자 플로우 (URL 입력 → 리포트 생성) 코드 레벨 추적
    
    산출:
    - _workspace/04_qa_report.md (발견 이슈 + 심각도 + 담당 에이전트)
    - _workspace/04_qa_checklist.md
    """
)
```

### Phase 4: 이슈 수정 및 정리

1. QA 리포트(`_workspace/04_qa_report.md`) 읽기
2. Critical 이슈: 담당 에이전트 서브 에이전트로 재호출하여 수정
3. 수정 완료 후 QA 에이전트 재검증 (담당 영역만)
4. `_workspace/` 보존 (삭제 금지)
5. 사용자에게 결과 요약 보고

## 데이터 흐름

```
[오케스트레이터]
    ↓ (서브)
[architect] → _workspace/01_architect_*.md/.sql
    ↓ (팀)
[backend] ←SendMessage→ [frontend]
    ↑ SendMessage         ↑ SendMessage  
[vision] ←SendMessage→ [backend]
    ↓
_workspace/02_backend_endpoints.md
_workspace/02_vision_output-schema.json
_workspace/03_frontend_pages.md
    ↓ (서브)
[qa] → _workspace/04_qa_report.md
    ↓
[오케스트레이터: 최종 요약]
```

## 에러 핸들링

| 상황 | 전략 |
|------|------|
| architect 설계 실패 | 사용자에게 알리고 재시작 여부 확인 |
| 팀원 1명 블로킹 | SendMessage로 상태 확인 → 재시작 또는 작업 재할당 |
| backend-frontend 인터페이스 충돌 | 두 에이전트를 동시 소환하여 협의 → architect 중재 |
| QA Critical 이슈 과다 (5개 이상) | 사용자에게 알리고 우선순위 결정 후 수정 진행 |
| vision 랜드마크 감지 실패 | Phase 1만 완성 후 Phase 2 재도전으로 범위 축소 제안 |

## 테스트 시나리오

### 정상 흐름 (Phase 1 MVP)
1. 사용자: "Phase 1 MVP를 구현해줘"
2. Phase 0: _workspace/ 없음 → 초기 실행
3. Phase 1: architect가 시스템 설계 완료 (3개 파일 생성)
4. Phase 2: 팀 구성 — backend(4개 작업) + frontend(4개 작업), vision은 대기
5. backend가 YouTube 파싱 엔드포인트 완료 → frontend에게 SendMessage
6. frontend가 메인 대시보드 페이지 구현 → qa에게 알림
7. Phase 3: qa가 경계면 검증 → 이슈 3개 발견 (Severity: Low 2, Medium 1)
8. Phase 4: Medium 이슈 수정 → qa 재검증 통과
9. 예상 결과: 동작하는 Phase 1 코드베이스 + `_workspace/04_qa_report.md`

### 에러 흐름 (backend 블로킹)
1. Phase 2에서 backend가 yt-dlp 오디오 처리 중 블로킹
2. 리더가 유휴 알림 수신
3. SendMessage("backend", "현재 상태 보고")
4. 오디오 폴백 부분만 스킵하고 자막 전용 엔드포인트 먼저 완성 지시
5. 자막 있는 영상 테스트는 가능한 상태로 Phase 3 진행
6. QA 리포트에 "yt-dlp 폴백 미구현" 명시

### 후속 작업 (부분 수정)
1. 사용자: "카드 UI 색상을 바꿔줘"
2. Phase 0: _workspace/ 존재 → 부분 재실행 판별
3. frontend 에이전트만 서브 에이전트로 재호출
4. `_workspace/03_frontend_pages.md` 읽어 수정 대상 파일 확인 후 변경
