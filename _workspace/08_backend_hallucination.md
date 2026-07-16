# 08. 할루시네이션 최소화 파이프라인 — 설계/결정 기록

작성: backend 에이전트 / 2026-07-16
브랜치: `claude/tennis-lesson-analysis-qx3p2y`

## 1. 문제 정의

기존 3개 경로 모두 "LLM이 오디오를 듣고 판단"하는 단계에서 코치가 말하지 않은
내용이 카드/타임스탬프에 생성되는 할루시네이션이 발생했다.

| 기존 경로 | 구조 | 할루시네이션 원인 |
|---|---|---|
| `gemini` (구 기본) | 20초 오디오 청크를 Gemini가 직접 듣고 전사+추출 | 전사 단계 자체가 LLM — 무음/공소리 구간에서 창작 |
| `gemini-youtube` | YouTube URL을 Gemini에 직접 전달 | 가장 심함 (영상 전체를 추정으로 재구성) |
| `whisper` (구 구현) | faster-whisper 전사 → Gemini 요약 | VAD/필터 전무 → Whisper 환청이 그대로 유입 |

## 2. 새 설계 원칙

**"LLM이 오디오를 듣고 판단"하는 구조를 폐기하고 3단으로 분리:**

```
yt-dlp 오디오 다운로드
  → [1] 신뢰 가능한 STT 전사 (환청 억제 + 코드 레벨 세그먼트 필터)
  → [2] LLM(Gemini)은 전사 텍스트의 "구조화만" 담당 (temperature=0.0)
  → [3] 코드 레벨 인용 검증 게이트 (전사에 없는 내용 자동 폐기)
```

LLM이 프롬프트를 어기고 내용을 지어내도 [3]에서 전량 폐기되므로,
할루시네이션이 최종 리포트에 도달할 수 있는 경로가 구조적으로 없다.

기본 `TRANSCRIPT_ENGINE`을 `whisper`(이 경로)로 변경했다.
(`whisper-verified`는 동일 경로 별칭. `gemini`/`gemini-youtube`는 폴백으로 유지.)

## 3. [1] STT 강화 — `app/services/stt_providers.py`, `stt_filters.py`

### 전사 파라미터 (faster-whisper, `STT_PROVIDER=local`)

| 파라미터 | 값 | 근거 |
|---|---|---|
| `vad_filter` | `True` (min_silence 500ms, pad 400ms) | 무음/공 소리 구간을 모델에 넣지 않아 창작 자체를 차단 |
| `condition_on_previous_text` | `False` | 이전 창의 환청이 다음 창으로 전파(반복 루프)되는 것 차단 |
| `temperature` | `0.0` | 샘플링 기반 창작 차단 |
| `beam_size` | 5 | 정확도 유지 |

### 세그먼트 필터 임계값 (`stt_filters.filter_hallucinated_segments`)

openai/whisper 기본값 = faster-whisper 커뮤니티 표준 권장값을 그대로 채택
([openai/whisper Discussion #2420](https://github.com/openai/whisper/discussions/2420),
[SYSTRAN/faster-whisper transcribe.py](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py)):

| 지표 | 제거 조건 | 의미 |
|---|---|---|
| `no_speech_prob` | > **0.6** | 무음 구간 창작 의심 |
| `avg_logprob` | < **-1.0** | 디코더가 자신 없는 저품질 세그먼트 |
| `compression_ratio` | > **2.4** | 텍스트/gzip 비율 — 반복 루프 환청의 대표 신호 |
| 연속 반복 dedupe | 정규화 유사도 ≥ **0.9** | 직전 통과 세그먼트와 동일/유사 텍스트 반복 제거 |

- 지표가 None(프로바이더 미제공)이면 해당 규칙은 건너뛴다.
- 필터링 통계(`total/kept/dropped_*`)는 로그 + 리포트 메타(`stt_stats`)에 기록된다.
- temperature를 0.0 단일값으로 고정하면 faster-whisper 내부의 temperature-fallback
  재디코딩이 발생하지 않아 임계값 초과 세그먼트가 그대로 반환되므로,
  **후단 코드 필터가 필수**다 (전사 라이브러리 임계값에만 의존하지 않음).

### STT 프로바이더 추상화 (`STT_PROVIDER: local | groq`)

Cloud Run CPU에서 faster-whisper medium은 1시간 영상에 비현실적으로 느리다
(실시간 대비 수 배). 호스티드 옵션으로 **Groq whisper-large-v3-turbo**를 추가:

- 가격: **$0.04/오디오시간** ([Groq Pricing](https://groq.com/pricing)) — 1시간 레슨 ≈ 55원
- 무료 티어: **2,000 요청/일 + 7,200 오디오초/시간** ([Groq 무료 티어](https://www.grizzlypeaksoftware.com/articles/p/groq-api-free-tier-limits-in-2026-what-you-actually-get-uwysd6mb)) — 저볼륨 운영은 무료로 커버 가능
- 한국어: whisper-large-v3 계열 다국어 지원 (한국어 포함)
- `response_format=verbose_json` → 세그먼트별 `start/end/avg_logprob/compression_ratio/no_speech_prob` 제공
  ([Groq Speech-to-Text 문서](https://console.groq.com/docs/speech-to-text)) → **local과 동일한 환청 필터 적용 가능**
- 파일 한도: free tier 25MB / dev tier 100MB → 16kHz mono 32kbps mp3 재인코딩
  (1시간 ≈ 14.4MB) 후 30분 청크로 분할 업로드, 세그먼트 타임스탬프에 오프셋 보정
- 호출: httpx로 OpenAI 호환 엔드포인트 직접 호출 (`https://api.groq.com/openai/v1/audio/transcriptions`) — SDK 의존성 추가 없음

대안 검토: OpenAI Whisper API($0.006/분 = $0.36/시간, Groq의 9배),
Deepgram/AssemblyAI(세그먼트별 품질 지표 미제공 또는 고가) → Groq 채택.

## 4. [2] Grounded 구조화 — `gemini_service.generate_lesson_report_whisper`

- 전사 텍스트(`[시작초~종료초] 발화` 라인 포맷)만 Gemini에 전달. 오디오/영상 미전달.
- `temperature=0.0`, thinking 비활성.
- 프롬프트(`WHISPER_VERIFIED_PROMPT`)에 명시:
  - "전사 스크립트에 없는 내용은 한 글자도 쓰지 마세요"
  - 모든 `timestamps[].quote`는 스크립트 원문 연속 구간을 그대로 복사
  - **card1/2/3에 각각 근거 인용 필드(`card1_evidence`~`card3_evidence`) 요구**
  - `sec`는 해당 quote가 포함된 줄의 시작초 그대로 (추정 금지)

## 5. [3] 인용 검증 게이트 — `app/services/verification.py` (핵심)

순수 함수 모듈 (외부 의존성 없음 → 네트워크 없이 pytest 실행 가능).

### 매칭 알고리즘 (`find_quote_match`)
1. 정규화: 소문자화 + 한글/영숫자 외 문자 제거 (STT/LLM의 띄어쓰기·문장부호 차이 흡수)
2. 인용이 여러 세그먼트에 걸칠 수 있으므로 연속 세그먼트 최대 3개 병합 창으로 비교
3. 점수: 부분 문자열 포함 = 1.0, 아니면 `difflib.SequenceMatcher` ratio
   (창이 인용보다 길면 인용 길이 슬라이딩 부분 문자열과도 비교해 부당 감점 방지)
4. 병합 창의 첫 세그먼트가 매칭에 기여하지 않으면 그 시작점 후보 폐기
   (시작초가 과도하게 앞당겨지는 것 방지)
5. 동일 발화가 여러 번 등장하면 LLM이 주장한 `sec`(hint)에 가장 가까운 발생 선택

### 판정 규칙 (`verify_report`)
| 대상 | 매칭 성공 | 매칭 실패 |
|---|---|---|
| `timestamps[]` | 유지 + **sec를 매칭 세그먼트 실제 시작초로 재계산** + `match_score` 부여 | **항목 폐기** |
| `cardN` (evidence 기준) | 카드 유지 | **카드 내용 폐기(null)** — evidence 누락도 실패로 간주 |

- 임계값: `VERIFY_MATCH_THRESHOLD=0.75` (config, 기본값).
  프롬프트가 "원문 그대로 복사"를 요구하므로 정상 인용은 정규화 후 1.0에 수렴 —
  0.75는 STT 표기 차이만 허용하고 의역/창작은 차단하는 보수적 값.
- 정규화 후 4자 미만 인용은 아무 데나 매칭되므로 검증 불가로 폐기.
- 통과/폐기 건수는 로그 + 리포트 메타(`verification`)에 기록.

## 6. API 호환성

- `lesson_reports` 응답 shape 변경 없음. 추가된 것:
  - `timestamps[].match_score` (additive, whisper 경로에서만)
  - `transcript_source`가 whisper 경로에서 `"WHISPER_STT"`로 채워짐 (기존 Literal에 이미 존재)
  - 리포트 dict의 `stt_stats`/`verification`/`transcript_text`는 파이프라인 내부 메타 —
    DB 컬럼이 없어 저장은 생략하고 로그로만 남긴다 (추후 마이그레이션 시 저장 가능).

## 7. 변경 파일

| 파일 | 변경 |
|---|---|
| `backend/app/services/stt_filters.py` | 신규 — 세그먼트 표현 + 환청 필터 (순수 함수) |
| `backend/app/services/stt_providers.py` | 신규 — STT 프로바이더 추상화 (local/groq) |
| `backend/app/services/verification.py` | 신규 — 인용 검증 게이트 (순수 함수) |
| `backend/app/services/gemini_service.py` | whisper 경로를 검증 파이프라인으로 재작성 |
| `backend/app/services/stt_service.py` | stt_providers 위임 + 쿠키/프록시 헬퍼 적용 |
| `backend/app/services/yt_dlp_helpers.py` | `YTDLP_PROXY` 프록시 지원 (자격증명 마스킹 로그) |
| `backend/app/routers/lessons.py` | 엔진 별칭 처리 + `transcript_source=WHISPER_STT` |
| `backend/app/config.py` | `STT_PROVIDER`, `GROQ_*`, `VERIFY_MATCH_THRESHOLD`, `YTDLP_PROXY`, 기본 엔진 변경 |
| `backend/requirements.txt` | `openai-whisper` → `faster-whisper` (코드는 원래 faster-whisper 사용) |
| `backend/.env.example` | 신규 설정 반영 |
| `backend/tests/test_stt_filters.py` | 신규 — 필터 단위 테스트 |
| `backend/tests/test_verification.py` | 신규 — 검증기 단위 테스트 |

## 8. 테스트

```bash
cd backend && python3 -m pytest tests/ -q
# 31 passed — 네트워크/모델/API 키 불필요
```

## 9. 남은 리스크 / 후속 과제

- STT 자체가 잘못 알아들은 내용(오인식)은 검증 게이트가 잡을 수 없다 —
  단, "코치가 말하지 않은 내용의 창작"과 달리 원문 근거는 존재한다.
- 검증 폐기율이 높은 영상(잡음 심함)은 카드가 null로 남을 수 있다 —
  프론트에서 "근거 부족" UX 처리 필요 시 frontend 에이전트와 협의.
- `verification`/`stt_stats` 메타의 DB 영속화는 별도 마이그레이션으로 후속 처리 가능.
