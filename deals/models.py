import re

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from clients.models import Client


def normalize_project_code(value: str) -> str:
    return re.sub(r'\s+', ' ', value.strip().lower())


def build_project_code_from_parts(module_count: int, client_part: str, site_part: str) -> str:
    client_segment = re.sub(r'\s+', ' ', (client_part or '').strip())
    site_segment = re.sub(r'\s+', ' ', (site_part or '').strip())
    return f'{module_count}МД-{client_segment}-{site_segment}'


class Deal(models.Model):
    class Status(models.TextChoices):
        ORPHAN = 'orphan', 'Orphan'
        NEW = 'new', 'New'
        QUALIFIED = 'qualified', 'Qualified'
        SENT_QUOTE = 'sent_quote', 'Sent quote'
        CONTRACT = 'contract', 'Contract'
        PREPAYMENT = 'prepayment', 'Prepayment'
        PRODUCTION = 'production', 'Production'
        INSTALLATION = 'installation', 'Installation'
        DELIVERED = 'delivered', 'Delivered'
        LOST = 'lost', 'Lost'

    project_code = models.CharField(max_length=200, unique=True, verbose_name='Код проекта')
    project_code_normalized = models.CharField(max_length=200, unique=True, db_index=True)
    code_client_name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Фамилия / компания (в коде проекта)',
    )
    code_site_name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Название участка (в коде проекта)',
    )
    module_count = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(15)]
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deals',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    assigned_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_deals',
    )
    margin_percent = models.DecimalField(max_digits=5, decimal_places=2, default=30)
    mortgage_required = models.BooleanField(default=False, verbose_name='Ипотека')
    target_deal_date = models.DateField(null=True, blank=True, verbose_name='Срок выхода на сделку')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.project_code_normalized = normalize_project_code(self.project_code)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.project_code

    def create_new_version(self, source='manual', created_by=None):
        last_version = self.versions.order_by('-version_number').first()
        next_number = 1 if last_version is None else last_version.version_number + 1
        return ProjectVersion.objects.create(
            deal=self,
            version_number=next_number,
            source=source,
            created_by=created_by,
        )


class ProjectVersion(models.Model):
    class Source(models.TextChoices):
        ARCHICAD = 'archicad', 'ArchiCAD'
        MANUAL = 'manual', 'Manual'
        CLIENT_REVISION = 'client_revision', 'Client revision'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SENT_TO_CLIENT = 'sent_to_client', 'Sent to client'
        ACCEPTED = 'accepted', 'Accepted'
        SUPERSEDED = 'superseded', 'Superseded'

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name='versions')
    version_number = models.PositiveIntegerField()
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    frozen_data = models.JSONField(null=True, blank=True)
    plan_pdf_path = models.CharField(max_length=500, null=True, blank=True)
    plan_preview_png_path = models.CharField(max_length=500, null=True, blank=True)
    plan_uploaded_at = models.DateTimeField(null=True, blank=True)
    quote_pdf_path = models.CharField(max_length=500, null=True, blank=True)
    quote_sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_project_versions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['deal', 'version_number'], name='uniq_deal_version_number')
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.deal.project_code} v{self.version_number}'


class ChangeLog(models.Model):
    project_version = models.ForeignKey(
        ProjectVersion,
        on_delete=models.CASCADE,
        related_name='change_logs',
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='change_logs',
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    field_path = models.CharField(max_length=255)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['-changed_at']

    def __str__(self):
        return f'{self.project_version} | {self.field_path}'
