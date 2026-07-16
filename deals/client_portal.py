import hashlib
import secrets
from datetime import timedelta

from django.utils import timezone

from .models import DealClientPortalSession


SESSION_TTL = timedelta(days=7)


def _hash_with_salt(value: str, *, salt: str) -> str:
    raw = (salt + '|' + (value or '')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def create_portal_session(*, deal, email: str) -> str:
    normalized_email = (email or '').strip().lower()
    now = timezone.now()
    token = secrets.token_urlsafe(32)
    token_salt = secrets.token_hex(8)
    token_hash = _hash_with_salt(token, salt=token_salt)
    DealClientPortalSession.objects.create(
        deal=deal,
        email=normalized_email,
        session_token_hash=f'{token_salt}${token_hash}',
        expires_at=now + SESSION_TTL,
        last_seen_at=now,
    )
    return token


def get_portal_session(*, deal, token: str) -> DealClientPortalSession | None:
    raw = (token or '').strip()
    if not raw:
        return None
    now = timezone.now()
    # We stored salt$hash; compare by hashing raw with stored salt.
    candidates = DealClientPortalSession.objects.filter(deal=deal, expires_at__gt=now).order_by('-created_at')[:50]
    for session in candidates:
        try:
            salt, expected_hash = (session.session_token_hash or '').split('$', 1)
        except ValueError:
            continue
        if _hash_with_salt(raw, salt=salt) == expected_hash:
            return session
    return None


def touch_session(session: DealClientPortalSession) -> None:
    session.last_seen_at = timezone.now()
    session.save(update_fields=['last_seen_at'])

