from decimal import Decimal, InvalidOperation

from django.utils import timezone

from .models import PlatformJob, SystemConfig


DEFAULT_SYSTEM_CONFIG = {
    SystemConfig.Key.DEFAULT_MARGIN_PERCENT: '30',
    SystemConfig.Key.STALE_DEAL_DAYS: '7',
    SystemConfig.Key.TASK_REMINDER_HOURS: '24',
}


def get_system_config_value(key: str, default: str | None = None) -> str:
    config = SystemConfig.objects.filter(key=key).only('value').first()
    if config is not None and config.value != '':
        return config.value
    if default is not None:
        return default
    return DEFAULT_SYSTEM_CONFIG.get(key, '')


def set_system_config_value(*, key: str, value: str, user=None) -> SystemConfig:
    config, _ = SystemConfig.objects.get_or_create(key=key)
    config.value = value
    config.updated_by = user
    config.save(update_fields=['value', 'updated_by', 'updated_at'])
    return config


def get_decimal_system_config(key: str, default: str) -> Decimal:
    raw_value = get_system_config_value(key, default)
    try:
        return Decimal(str(raw_value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def get_int_system_config(key: str, default: int) -> int:
    raw_value = get_system_config_value(key, str(default))
    try:
        return int(str(raw_value))
    except (TypeError, ValueError):
        return default


def get_default_margin_percent() -> Decimal:
    return get_decimal_system_config(SystemConfig.Key.DEFAULT_MARGIN_PERCENT, '30')


def enqueue_platform_job(*, job_type: str, payload: dict | None = None, run_after=None) -> PlatformJob:
    return PlatformJob.objects.create(
        job_type=job_type,
        payload=payload or {},
        run_after=run_after or timezone.now(),
    )
