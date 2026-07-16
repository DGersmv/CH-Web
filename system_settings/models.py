import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class SystemConfig(models.Model):
    class Key(models.TextChoices):
        DEFAULT_MARGIN_PERCENT = 'default_margin_percent', 'Default margin percent'
        STALE_DEAL_DAYS = 'stale_deal_days', 'Stale deal days'
        TASK_REMINDER_HOURS = 'task_reminder_hours', 'Task reminder hours'

    key = models.CharField(max_length=100, unique=True, choices=Key.choices)
    value = models.CharField(max_length=255, blank=True, default='')
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_system_configs',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['key']

    def __str__(self):
        return self.key


class IntegrationToken(models.Model):
    name = models.CharField(max_length=120)
    key = models.CharField(max_length=64, unique=True, db_index=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='integration_tokens',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_integration_tokens',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['name', '-created_at']

    def __str__(self):
        return self.name

    @property
    def masked_key(self) -> str:
        if len(self.key) < 8:
            return self.key
        return f'{self.key[:4]}...{self.key[-4:]}'

    @classmethod
    def create_token(cls, *, name: str, owner, created_by):
        token = cls(
            name=name.strip(),
            owner=owner,
            created_by=created_by,
            key=secrets.token_hex(24),
        )
        token.save()
        return token


class PlatformJob(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'

    job_type = models.CharField(max_length=100)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    run_after = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['run_after', 'created_at']
        indexes = [
            models.Index(fields=['status', 'run_after'], name='platform_job_due_idx'),
        ]

    def __str__(self):
        return f'{self.job_type} [{self.status}]'
