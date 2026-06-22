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

    # === yt-dlp ===
    YTDLP_FORMAT: str = "bestaudio/best"
    YTDLP_MAX_DURATION_SEC: int = 5400

    # === 분석 파이프라인 ===
    ANALYZE_TIMEOUT_SEC: int = 600
    TRANSCRIPT_PREFERRED_LANGUAGES: str = "ko,ko-KR,en"

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
