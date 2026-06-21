"""Supabase 클라이언트 초기화 (싱글톤)."""

from functools import lru_cache
from typing import Optional

from supabase import Client, create_client

from app.config import get_settings


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """service_role 키로 인증된 Supabase 클라이언트를 반환한다.

    RLS를 우회하므로 백엔드 서버 사이드에서만 사용한다.
    """
    settings = get_settings()
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL 과 SUPABASE_SERVICE_ROLE_KEY 환경변수가 설정되어야 합니다."
        )

    client: Client = create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_ROLE_KEY,
    )
    return client


def reset_supabase_client() -> None:
    """테스트/재초기화 용 캐시 클리어."""
    get_supabase_client.cache_clear()
