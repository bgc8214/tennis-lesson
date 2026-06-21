"""Supabase JWT 검증 의존성.

Supabase는 ES256 (비대칭키) 알고리즘을 사용한다.
JWKS 엔드포인트에서 공개키를 가져와 검증한다.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_jwks_public_keys() -> dict:
    """Supabase JWKS 엔드포인트에서 공개키 목록을 가져온다 (캐시)."""
    import urllib.request, json
    settings = get_settings()
    jwks_url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    try:
        res = urllib.request.urlopen(jwks_url, timeout=5)
        jwks = json.loads(res.read())
        # kid → 공개키 객체 매핑
        from jwt.algorithms import ECAlgorithm
        keys = {}
        for key_data in jwks.get("keys", []):
            kid = key_data.get("kid")
            if kid:
                keys[kid] = ECAlgorithm.from_jwk(key_data)
        logger.info("JWKS 공개키 로드 완료: %d개", len(keys))
        return keys
    except Exception as e:
        logger.error("JWKS 로드 실패: %s", e)
        return {}


def _decode_jwt(token: str) -> dict:
    try:
        import jwt
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": {"code": "INTERNAL_ERROR", "message": f"PyJWT import failed: {e}"}},
        )

    # 토큰 헤더에서 kid, alg 추출
    try:
        header = jwt.get_unverified_header(token)
    except Exception as e:
        logger.info("JWT 헤더 파싱 실패: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "UNAUTHENTICATED", "message": "유효하지 않은 인증 토큰입니다."}},
        )

    alg = header.get("alg", "")
    kid = header.get("kid")

    # ES256 (현재 Supabase 기본값)
    if alg == "ES256":
        public_keys = _get_jwks_public_keys()
        if not public_keys:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": {"code": "INTERNAL_ERROR", "message": "공개키를 가져올 수 없습니다."}},
            )
        public_key = public_keys.get(kid) if kid else next(iter(public_keys.values()), None)
        if not public_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "UNAUTHENTICATED", "message": "유효하지 않은 인증 토큰입니다."}},
            )
        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["ES256"],
                audience="authenticated",
                options={"verify_aud": True},
            )
            return payload
        except jwt.exceptions.InvalidAudienceError:
            payload = jwt.decode(token, public_key, algorithms=["ES256"], options={"verify_aud": False})
            return payload
        except Exception as e:
            logger.info("ES256 JWT 검증 실패: %s", e)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "UNAUTHENTICATED", "message": "유효하지 않은 인증 토큰입니다."}},
            )

    # HS256 / HS512 (구버전 Supabase)
    elif alg in ("HS256", "HS512"):
        import base64
        settings = get_settings()
        try:
            secret_bytes = base64.b64decode(settings.SUPABASE_JWT_SECRET + "==")
        except Exception:
            secret_bytes = settings.SUPABASE_JWT_SECRET.encode()
        try:
            payload = jwt.decode(
                token, secret_bytes, algorithms=[alg],
                audience="authenticated", options={"verify_aud": True},
            )
            return payload
        except jwt.exceptions.InvalidAudienceError:
            payload = jwt.decode(token, secret_bytes, algorithms=[alg], options={"verify_aud": False})
            return payload
        except Exception as e:
            logger.info("HS JWT 검증 실패: %s", e)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "UNAUTHENTICATED", "message": "유효하지 않은 인증 토큰입니다."}},
            )

    else:
        logger.info("지원하지 않는 JWT 알고리즘: %s", alg)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "UNAUTHENTICATED", "message": "유효하지 않은 인증 토큰입니다."}},
        )


ANONYMOUS_USER_ID = "00000000-0000-0000-0000-000000000000"


def get_current_user_id(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> str:
    if not authorization:
        return ANONYMOUS_USER_ID

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ANONYMOUS_USER_ID

    try:
        payload = _decode_jwt(parts[1])
    except HTTPException:
        return ANONYMOUS_USER_ID

    user_id = payload.get("sub")
    if not user_id:
        return ANONYMOUS_USER_ID
    return str(user_id)


CurrentUserId = Depends(get_current_user_id)
