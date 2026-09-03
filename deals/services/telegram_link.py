"""Одноразовые коды привязки Telegram к пользователю CRM."""
from __future__ import annotations

import secrets

from django.utils import timezone

from deals.models import TelegramProfile

CODE_TTL_MINUTES = 15
_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # без похожих символов


def get_profile(user) -> TelegramProfile:
    profile, _ = TelegramProfile.objects.get_or_create(user=user)
    return profile


def issue_code(user) -> TelegramProfile:
    profile = get_profile(user)
    profile.link_code = ''.join(secrets.choice(_ALPHABET) for _ in range(6))
    profile.link_code_expires_at = timezone.now() + timezone.timedelta(minutes=CODE_TTL_MINUTES)
    profile.save(update_fields=['link_code', 'link_code_expires_at'])
    return profile


def unlink(user) -> None:
    profile = get_profile(user)
    profile.telegram_user_id = None
    profile.telegram_username = ''
    profile.link_code = ''
    profile.link_code_expires_at = None
    profile.linked_at = None
    profile.save()
