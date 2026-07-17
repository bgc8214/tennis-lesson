"""환경변수 설정 (pydantic-settings 기반)."""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """애플리케이션 환경 설정.

    `.env` 파일 또는 OS 환경변수에서 자동 로드된다.
    모든 시크릿(GEMINI_API_KEY, SUPABASE_*)은 코드에 하드코딩 금지.
    """

    # === 앱 기본 ===
    APP_ENV: str = "development"
    APP_NAME: str = "tennis-lesson-api"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # === CORS ===
    # 콤마 구분 문자열로 받아 list로 변환
    CORS_ALLOW_ORIGINS: str = "http://localhost:3000"

    # === Supabase ===
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_JWT_SECRET: str = ""

    # === Google Gemini ===
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"
    GEMINI_MAX_OUTPUT_TOKENS: int = 2048
    GEMINI_TEMPERATURE: float = 0.4

    # === Whisper ===
    WHISPER_MODEL_SIZE: str = "medium"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_LANGUAGE: str = "ko"

    # === STT 프로바이더 ===
    # local: faster-whisper 로컬 추론 (무료, CPU에서 느림)
    # groq : Groq 호스티드 whisper-large-v3-turbo ($0.04/오디오시간, 무료 티어 있음)
    STT_PROVIDER: str = "local"
    GROQ_API_KEY: str = ""
    GROQ_STT_MODEL: str = "whisper-large-v3-turbo"

    # === 인용 검증 (할루시네이션 게이트) ===
    # LLM 인용 vs 전사 원문 fuzzy match 통과 임계값 (정규화 텍스트 기준)
    VERIFY_MATCH_THRESHOLD: float = 0.75

    # === STT 전사 품질 (09문서 1-1/1-2) ===
    # STT initial_prompt에 테니스 용어 사전을 주입할지 여부.
    STT_TERM_HINT_ENABLED: bool = True
    # 코트 원거리 마이크 저볼륨(mean -27~-40dB 실측) 보정을 위한 오디오 전처리
    # (highpass + loudnorm) 활성화 여부. compression_ratio 필터 오탐 가능성이
    # 있어 골든셋 A/B로 검증 전에는 기본 False로 시작.
    AUDIO_PREPROCESS_ENABLED: bool = False

    # === yt-dlp ===
    YTDLP_FORMAT: str = "bestaudio/best"
    YTDLP_MAX_DURATION_SEC: int = 5400
    # Cloud Run 등 데이터센터 IP에서 YouTube 봇 감지 우회용 프록시 URL.
    # 예: http://user:pass@gate.example-residential-proxy.com:7777
    YTDLP_PROXY: str = ""

    # === 분석 파이프라인 ===
    ANALYZE_TIMEOUT_SEC: int = 600
    TRANSCRIPT_PREFERRED_LANGUAGES: str = "ko,ko-KR,en"
    # whisper: STT 전사 → Gemini는 구조화만 → 코드 레벨 인용 검증 (기본, 할루시네이션 최소)
    #          ("whisper-verified"도 동일 경로의 별칭)
    # gemini: 오디오 직접 업로드 후 Gemini가 청크별 전사+추출 (폴백)
    # gemini-youtube: Gemini에 public YouTube URL 직접 전달 (yt-dlp 미사용, 할루시네이션 큼)
    TRANSCRIPT_ENGINE: str = "whisper"

    # === Court Analysis (Phase 2) ===
    COURT_ANALYSIS_ENABLED: bool = False  # 기본값 False (점진적 롤아웃)
    COURT_ANALYSIS_MAX_CLIPS: int = 10
    COURT_ANALYSIS_CLIP_DURATION: int = 40
    COURT_ANALYSIS_VIDEO_HEIGHT: int = 480
    COURT_ANALYSIS_YOLO_CONF: float = 0.5
    COURT_ANALYSIS_FPS_SAMPLE: int = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ALLOW_ORIGINS.split(",") if o.strip()]

    @property
    def transcript_languages(self) -> List[str]:
        return [
            lang.strip()
            for lang in self.TRANSCRIPT_PREFERRED_LANGUAGES.split(",")
            if lang.strip()
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """싱글톤 설정 인스턴스 반환."""
    return Settings()
