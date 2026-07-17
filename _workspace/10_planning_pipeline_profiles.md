# 10. 실행 환경 프로파일 분리 기획 — 로컬(최고 품질) / 서버 무료 / 서버 유료

작성: 오케스트레이터 세션 / 2026-07-17
브랜치: `claude/tennis-lesson-analysis-qx3p2y`
상태: **기획만 완료, 구현 없음** — 구현 위임 시 이 문서의 섹션 번호로 지시
선행 문서: `08_deployment_hallucination.md`(비용/봇감지 리서치), `09_planning_quality_and_features.md`(품질 개선 항목)

## 1. 목적

같은 코드베이스를 세 가지 운영 환경에서 다른 전략으로 돌린다:

| 프로파일 | 환경 | 원칙 |
|---|---|---|
| `local-max` | 로컬 머신 (도그푸딩/품질 기준선) | 어차피 무료 — **품질 최대화**, 시간 아끼지 않음 |
| `server-free` | Cloud Run | **비용 0원 강제** — 무료 티어만 조합, 성공률/품질 타협 감수 |
| `server-paid` | Cloud Run | 소액 유료 허용 — **안정성/품질 우선** (회당 ~130원, 08문서 근거) |

핵심 설계 사상: 프로파일은 **기존 개별 설정들의 "기본값 묶음"**일 뿐,
새로운 파이프라인을 만드는 게 아니다. 코드 경로는 기존
whisper(검증)/gemini/gemini-youtube 3개를 그대로 쓰고, 프로파일이
어떤 경로·어떤 STT·어떤 옵션으로 조합할지만 결정한다.

## 2. 프로파일별 상세 스펙

### 2-1. `local-max` — 로컬 최고 품질 (무료)

| 항목 | 값 | 근거 |
|---|---|---|
| TRANSCRIPT_ENGINE | `whisper` (검증 경로) | 할루시네이션 최소 경로 |
| STT_PROVIDER | `local` (faster-whisper) | 로컬 컴퓨트 무료 |
| WHISPER_MODEL_SIZE | **`large-v3`** (현행 medium에서 상향) | 저볼륨 한국어 오디오에서 medium 대비 인식률 우위. 로컬은 처리 시간이 길어져도 무방 (26분 영상 medium 기준 7분30초 실측 → large-v3는 2~3배 예상, **실측 필요**) |
| 오디오 전처리 | **on** — `highpass=f=100,loudnorm=I=-16:TP=-1.5:LRA=11` | 09문서 1-2. 실측 mean -27~-40dB 저볼륨 보정 → no_speech 폐기 186건 일부 복구 기대 |
| STT initial_prompt | **on** — 테니스 용어 사전 | 09문서 1-1 |
| Gemini 구조화 모델 | 상위 모델 허용 (별도 키 `GEMINI_MODEL_STRUCTURE`, 미설정 시 GEMINI_MODEL) | 전사 텍스트만 입력이라 토큰 소량. AI Studio 무료 티어 키면 0원 유지 |
| 프록시/쿠키 | 불필요 (주거용 IP로 yt-dlp 정상) | 실측 확인됨 |
| 실패 시 폴백 | **없음 — 실패 원인 그대로 노출** | 이 프로파일은 품질 기준선/디버깅 용도. 조용한 폴백은 품질 측정을 오염시킴 |

비고: "로컬=완전 무료"의 유일한 예외는 Gemini API 호출(로컬에서도 API로 나감).
AI Studio 무료 티어 키 사용 전제 — 초과 시에도 텍스트 구조화라 소액.

### 2-2. `server-free` — Cloud Run 비용 0원

| 항목 | 값 | 근거 |
|---|---|---|
| TRANSCRIPT_ENGINE | `whisper` 1차 시도 | 검증 경로 우선 |
| STT_PROVIDER | **`groq` (무료 티어)** | 핵심 판단: Groq free tier(2,000 req/일, 카드 등록 불필요)는 "비용 0원" 조건을 만족하면서 Cloud Run 약한 CPU 문제(local whisper는 처리 시간 폭증 + vCPU-초 무료 한도 소진)를 동시에 해결. **server-free의 병목은 STT가 아니라 오디오 획득(yt-dlp 봇 감지)임** |
| 오디오 전처리 / initial_prompt | on / on | ffmpeg는 비용 0, 품질만 상승 |
| 프록시 | 없음 (0원 원칙) — POT provider + 쿠키(`YT_COOKIES_B64`)만으로 시도 | 성공률 낮음을 감수 (데이터센터 IP 20~40%, 08문서) |
| **폴백 체인** | yt-dlp 오디오 다운로드 실패 시 → `gemini-youtube` (무료) | 실패를 그냥 FAILED로 두는 것보다 낫지만, 이 경로는 **검증 게이트 미적용**이므로 반드시 리포트에 표식 (3절 메타/UI 참조) |
| 근본 무료 해법 | 08문서 (b)안 — 로컬 worker 폴링 | server-free의 성공률 한계가 문제되면 (b)안 구현이 정답. 이 프로파일은 그 전까지의 차선책 |

### 2-3. `server-paid` — Cloud Run 유료 안정 운영

| 항목 | 값 | 근거 |
|---|---|---|
| TRANSCRIPT_ENGINE | `whisper` | 검증 경로 |
| STT_PROVIDER | `groq` | $0.04/오디오시간 (08문서) |
| 프록시 | **`YTDLP_PROXY` residential 필수** — 미설정 시 기동 시 경고 로그 (기동 실패까지는 아님) | 봇 감지 실질 해결책 (성공률 85~95%). 회당 ~$0.05 |
| 오디오 전처리 / initial_prompt | on / on | 동일 |
| 폴백 체인 | 프록시 경유 다운로드까지 실패 시 → `gemini-youtube` + 표식 | 가용성 우선 |
| 회당 원가 | ≈ $0.09 (~130원) | 08문서 산정 |
| Cloud Run 설정 전제 | CPU always-allocated (`--no-cpu-throttling`) 필수 | BackgroundTasks가 202 응답 후 실행되는 구조라, 스로틀링 상태면 백그라운드 분석이 멈춤 (기 논의) |

## 3. 설정/코드 구조 기획 (구현 에이전트용)

### 3-1. 설정 키 설계 (`backend/app/config.py`)

```
PIPELINE_PROFILE: str = ""        # "" | "local-max" | "server-free" | "server-paid"
AUDIO_PREPROCESS_ENABLED: bool    # 프로파일이 기본값 결정, 개별 env로 override 가능
STT_INITIAL_PROMPT_ENABLED: bool  # 동상
GEMINI_MODEL_STRUCTURE: str = ""  # 구조화(Pass B) 전용 모델, 빈 값이면 GEMINI_MODEL
```

**override 규칙 (중요)**: `PIPELINE_PROFILE`이 설정되면 프로파일 기본값을
적용하되, **개별 env 변수가 명시적으로 설정된 경우 개별 값이 항상 우선**한다.
빈 프로파일("")이면 현행 동작 그대로 (하위 호환 — 기존 배포에 무영향).
구현 방식 제안: Settings 로드 후 프로파일 기본값을 "env에 없던 필드에만"
채우는 resolver 함수 + 적용 결과를 기동 로그에 1줄 출력
(`profile=server-paid engine=whisper stt=groq preprocess=on proxy=set`).

### 3-2. 폴백 체인 (`backend/app/routers/lessons.py` `_run_analysis_pipeline`)

- 프로파일이 폴백 목록을 제공: `local-max=[whisper]`,
  `server-free/paid=[whisper, gemini-youtube]`
- **폴백 발동 조건을 좁게 정의**: 오디오 다운로드 실패(`audio_download_failed`,
  yt-dlp 예외)일 때만 다음 엔진으로. STT/Gemini/검증 단계 오류는 폴백하지 않고
  FAILED (원인 감춤 방지 — 폴백은 "오디오를 못 구했을 때"의 대체 수단이지
  오류 은폐 수단이 아님).
- 폴백 실행 시 `progress_message`에 "간이 분석으로 전환 중..." 반영.

### 3-3. 리포트 메타 + UI 표식

- 리포트 dict에 `pipeline_profile`, `engine_used` 추가 (기존 additive 원칙,
  09문서와 동일하게 DB 영속화는 선택 — 최소 `transcript_source`로 구분 가능:
  `WHISPER_STT` vs `GEMINI_YOUTUBE`).
- **UI 기획**: `engine_used=gemini-youtube`(폴백) 리포트에는
  "⚡ 간이 분석 — 발언 검증 미적용" 배지 + "정밀 재분석" 버튼
  (server-paid 전환 또는 로컬 worker 처리 유도). 검증 경로 리포트에는
  기존 match_score 뱃지. 신뢰 수준을 사용자에게 투명하게.

### 3-4. 이 기획이 포함하는 09문서 항목

- 09문서 **1-1(initial_prompt)**, **1-2(오디오 전처리)**는 프로파일 구성
  요소로 이번 구현 범위에 포함시킬 것 (플래그로 제어되므로 A/B 가능).
- 09문서 **1-3(골든셋)**을 먼저 만들면 전처리·모델 상향의 효과를 수치로
  확인 가능 — 같은 스프린트에 묶는 것을 권장.

## 4. 비용 요약

| | local-max | server-free | server-paid |
|---|---|---|---|
| yt-dlp | 0원 (주거 IP) | 0원 (성공률 낮음) | ~$0.05/회 (프록시) |
| STT | 0원 (로컬 large-v3) | 0원 (Groq free tier) | ~$0.04/회 (Groq) |
| Gemini | 무료 티어 | 무료 티어 | 무료 티어~소액 |
| **회당 합계** | **0원** | **0원** | **≈$0.09 (~130원)** |
| 성공률 | 높음 | 낮음 (폴백 시 품질↓) | 높음 |
| 품질 | **최고** (large-v3+전처리) | 성공 시 상, 폴백 시 하 | 상 |

## 5. 오픈 퀘스천 (구현 전 확인)

1. Cloud Run `--no-cpu-throttling` 설정 여부 — 확인 명령어는 기 전달, 미확인 상태.
2. large-v3 로컬 처리 시간 실측 (수용 가능 범위인지 — 26분 영상 기준).
3. 전처리(loudnorm) A/B — 골든셋(09문서 1-3) 선행 권장. 전처리가
   compression_ratio 필터 오탐을 유발하지 않는지 확인 항목 포함.
4. Groq free tier 실사용 한도가 서비스 초기 트래픽을 감당하는지
   (2,000요청/일 — 청크 분할 시 1영상=수 요청임을 감안).

## 6. 구현 위임 가이드

- 담당: backend 에이전트 단독 (3-3 UI 표식만 frontend 병행)
- 위임 시 지시 예: "10문서 2절+3절 구현, 09문서 1-1/1-2 포함, 골든셋(09문서
  1-3)은 별도 태스크"
- 완료 기준: 프로파일 resolver 단위 테스트(override 규칙 포함) + 기동 로그
  1줄 + `.env.example`에 프로파일별 샘플 3세트 주석
