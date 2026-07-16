# 08. 배포 가이드 — Cloud Run yt-dlp 봇 감지 해결 + 할루시네이션 최소 파이프라인 운영

작성: backend 에이전트 / 2026-07-16

## 1. 현황 정리

- **문제**: Cloud Run(데이터센터 IP)에서 yt-dlp가 YouTube "Sign in to confirm you're not a bot"에 걸림.
- **이미 적용됨**: bgutil PO Token provider(Dockerfile 내장, web/mweb 클라이언트), 쿠키(`YT_COOKIES_B64`) — 불충분.
- **로컬 머신에서는 yt-dlp 정상 동작** (주거용 IP).
- 사용자 우선순위: **할루시네이션 최소화 > 무료**.

### 2026년 현재 리서치 결론

- 데이터센터 IP 대역(GCP/AWS/Azure)은 YouTube가 대역 단위로 자동 플래그. PO Token + 쿠키만으로는
  성공률이 낮고, 쿠키는 수명 문제(주기적 만료·계정 리스크)가 있어 운영 해법이 못 됨.
- 업계 컨센서스: 프로덕션 클라우드 환경에서 신뢰 가능한 방법은 **residential proxy**뿐
  (데이터센터 프록시 성공률 20~40% vs residential 85~95%).
  참고: [DEV: Cloud video service와 YouTube 차단기](https://dev.to/osovsky/i-was-building-a-cloud-video-service-youtube-turned-me-into-an-ip-trafficker-1l9o),
  [PROXY001: yt-dlp 서버 워크로드 차단](https://proxy001.com/blog/youtube-proxy-prevent-server-ip-blocks-after-deploying-yt-dlp-style-server-workloads)
- 프록시 GB 단가 (2026): IPRoyal ~$1.75/GB PAYG, Webshare ~$1.4/GB(볼륨), Decodo ~$3.75/GB,
  DataImpulse ~$1/GB. 참고: [aimultiple 프록시 가격 비교](https://aimultiple.com/proxy-pricing),
  [IPRoyal 가격](https://iproyal.com/pricing/residential-proxies/)
- 무료 우회(Cloudflare WARP 컨테이너 등)는 존재하지만 비공식·불안정 — 서비스 운영 기준 부적합.

### 코드 레벨 준비 완료

`YTDLP_PROXY` 환경변수 설정 시 `yt_dlp_helpers.build_youtube_ydl_opts`가 모든 YouTube
트래픽을 해당 프록시로 라우팅한다 (오디오 다운로드 + 메타데이터 조회 공통 적용).

```bash
YTDLP_PROXY=http://user:pass@gate.provider.example:7777
```

## 2. 옵션 비교

### 회당 원가 계산 근거 (1시간 레슨 기준)

- 오디오 전용 다운로드(bestaudio m4a ~64kbps): **≈ 30MB = 0.03GB**
- 프록시 비용: 0.03GB × $1.75/GB(IPRoyal) ≈ **$0.05 (~75원)** / 회
- Groq STT(whisper-large-v3-turbo): $0.04/오디오시간 ≈ **$0.04 (~55원)** / 회
  (무료 티어: 2,000요청/일 + 7,200오디오초/시간 — 월 수십 건 수준은 사실상 무료)
- Gemini: 전사 텍스트 1회 호출 — 기존과 동일(무료 티어 내)

| | (a) Cloud Run + residential proxy + Groq STT | (b) 로컬 worker 폴링 (설계만) | (c) gemini-youtube 폴백 |
|---|---|---|---|
| yt-dlp 봇 감지 | 해결 (residential IP) | 해결 (집 IP, 이미 정상 동작 확인) | 해당 없음 (yt-dlp 미사용) |
| 할루시네이션 | **최소** (whisper 검증 파이프라인) | **최소** (동일 파이프라인) | **큼** (LLM이 영상 직접 해석) |
| 회당 비용 | ≈ $0.09 (~130원) | 0원 (전기/머신 제외) | 0원 |
| 월 비용 (월 30회) | ≈ $2.7 + 프록시 최소 충전\* | 0원 | 0원 |
| 월 비용 (월 300회) | ≈ $27 | 0원 | 0원 |
| 가용성 | Cloud Run 수준 (상시) | 로컬 머신 가동 시간에 종속 | Cloud Run 수준 |
| 지연 | 다운로드+STT 수십 초 | 폴링 주기 + 처리 시간 | 구간별 Gemini 호출 (분 단위) |
| 구현 상태 | **완료** (환경변수만 설정) | 설계만 (스코프 아웃) | 완료 (기존 경로) |

\* 프록시 업체 대부분 최소 충전 단위 존재 (IPRoyal PAYG 등 — 소액 선충전 후 이월 사용).

### 권장 시나리오

1. **프로덕션 기본 (권장)**: **(a)** — Cloud Run 환경변수 설정만으로 즉시 적용:
   ```
   TRANSCRIPT_ENGINE=whisper
   STT_PROVIDER=groq
   GROQ_API_KEY=gsk_...
   YTDLP_PROXY=http://user:pass@gate.provider.example:7777
   ```
   회당 ~130원은 "할루시네이션에 도움되면 유료 OK" 기준에 부합하는 소액.
   Cloud Run CPU에서 faster-whisper는 비현실적이므로 (a)에서 `STT_PROVIDER=local`은 금지.
2. **완전 무료가 필요해지면**: **(b)** 로컬 worker 구현 (아래 설계 참조).
3. **긴급 폴백**: (a)의 프록시/Groq 장애 시에만 **(c)** `TRANSCRIPT_ENGINE=gemini-youtube`로
   일시 전환. 할루시네이션 리스크를 사용자에게 고지할 것.

## 3. (b)안 설계 — 로컬 worker 폴링 (코드 구현은 스코프 아웃)

로컬 머신은 주거용 IP라 yt-dlp가 정상 동작한다는 점을 활용한다.
Cloud Run은 접수/조회 API만 담당하고, 무거운 다운로드·분석은 로컬 worker가 수행.

```
[사용자] → POST /lessons/analyze (Cloud Run)
             └ lessons + lesson_reports(PENDING) 생성만 하고 즉시 202 반환
[로컬 worker (집 머신, python 프로세스)]
  loop every N초:
    1. Supabase에서 processing_status=PENDING 행을 조회
       (경합 방지: UPDATE ... WHERE status='PENDING' RETURNING 으로 원자적 클레임,
        worker_id + claimed_at 기록)
    2. PROCESSING으로 전이 후 yt-dlp 오디오 다운로드 (로컬 IP — 봇 감지 없음)
    3. STT(local faster-whisper — 로컬 GPU/CPU 자유) → Gemini 구조화 → 인용 검증
       (backend 코드의 generate_lesson_report_whisper를 그대로 재사용)
    4. 결과를 lesson_reports에 UPDATE (DONE/FAILED), progress_*는 진행 중 갱신
    5. stale 클레임 회수: claimed_at이 T분 이상 경과한 PROCESSING 행은 PENDING으로 복구
```

- 인증: worker는 `SUPABASE_SERVICE_ROLE_KEY` 사용 (외부 노출 금지, 로컬 .env).
- Cloud Run 쪽 변경: `TRANSCRIPT_ENGINE=none`(신설) 또는 worker 모드 플래그로
  BackgroundTask 트리거만 생략하면 됨 — API 계약 변경 없음.
- 단점: 로컬 머신이 꺼져 있으면 잡이 대기 상태로 누적 → 프론트에 "대기 중" UX 필요.
- 하이브리드 운영 가능: worker가 일정 시간 내 클레임하지 않은 잡을 Cloud Run이
  (a) 경로로 회수하는 타임아웃 폴백.

## 4. 운영 체크리스트

- [ ] Groq 콘솔에서 API 키 발급 → Cloud Run 시크릿 `GROQ_API_KEY` 등록
- [ ] residential proxy 계정 개설(소액 PAYG) → `YTDLP_PROXY` 시크릿 등록
- [ ] Cloud Run 환경변수: `TRANSCRIPT_ENGINE=whisper`, `STT_PROVIDER=groq`
- [ ] 배포 후 로그에서 `[stt:groq]` 청크 수 / `[verify]` 통과·폐기 건수 확인
- [ ] 프록시 트래픽 대시보드에서 회당 사용량이 ~0.03GB 수준인지 확인
      (영상 다운로드가 아닌 오디오 전용인지 검증)
- [ ] 쿠키(`YT_COOKIES_B64`)는 프록시 적용 후에도 유지 (성공률 보조)
- 시크릿은 전부 환경변수/Secret Manager — 코드/이미지에 하드코딩 금지

## 5. 참고 자료

- [Groq Pricing](https://groq.com/pricing) — whisper-large-v3-turbo $0.04/시간
- [Groq Speech-to-Text 문서](https://console.groq.com/docs/speech-to-text) — verbose_json, 파일 한도 25MB(free)/100MB(dev)
- [Groq 무료 티어 한도](https://www.grizzlypeaksoftware.com/articles/p/groq-api-free-tier-limits-in-2026-what-you-actually-get-uwysd6mb)
- [aimultiple: 2026 프록시 가격 비교](https://aimultiple.com/proxy-pricing)
- [IPRoyal residential 가격](https://iproyal.com/pricing/residential-proxies/)
- [DEV: YouTube의 데이터센터 IP 차단 경험담](https://dev.to/osovsky/i-was-building-a-cloud-video-service-youtube-turned-me-into-an-ip-trafficker-1l9o)
