import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

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
        version = ProjectVersion.objects.create(
            deal=self,
            version_number=next_number,
            source=source,
            created_by=created_by,
        )
        from .services.storage_paths import ensure_version_dirs

        ensure_version_dirs(version)
        return version


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


class DealBathroom(models.Model):
    """Один санузел в рамках версии проекта (вкладка «Санузел №k»)."""

    deal = models.ForeignKey('Deal', on_delete=models.CASCADE, related_name='deal_bathrooms')
    project_version = models.ForeignKey(
        'ProjectVersion',
        on_delete=models.CASCADE,
        related_name='bathrooms',
    )
    index = models.PositiveSmallIntegerField()
    label = models.CharField(max_length=100, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['project_version', 'index'], name='uniq_project_version_bathroom_index'),
        ]
        ordering = ['index']

    def __str__(self):
        return f'{self.project_version} · санузел {self.index}'


class DealBathroomLine(models.Model):
    """Строка наполнения санузла (снимок из каталога)."""

    class LineKind(models.TextChoices):
        MATERIAL = 'material', 'Материал'
        WORK = 'work', 'Работа'
        MIXED = 'mixed', 'Смешанный'

    bathroom = models.ForeignKey(
        DealBathroom,
        on_delete=models.CASCADE,
        related_name='lines',
    )
    cost_item = models.ForeignKey(
        'catalog.CostItem',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='deal_bathroom_lines',
    )
    selected_option = models.ForeignKey(
        'catalog.CostItemOption',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='selected_bathroom_lines',
    )
    name_snapshot = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=LineKind.choices)
    is_included = models.BooleanField(default=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('1'))
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.bathroom} · {self.name_snapshot}'

    @property
    def line_total(self) -> Decimal:
        if not self.is_included:
            return Decimal('0')
        q = Decimal(str(self.quantity))
        p = Decimal(str(self.unit_price))
        return (q * p).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class DealAdditionalOptionLine(models.Model):
    """Строка раздела «Дополнительные опции» в рамках версии проекта."""

    class LineKind(models.TextChoices):
        MATERIAL = 'material', 'Материал'
        WORK = 'work', 'Работа'
        MIXED = 'mixed', 'Смешанный'

    project_version = models.ForeignKey(
        'ProjectVersion',
        on_delete=models.CASCADE,
        related_name='additional_option_lines',
    )
    cost_item = models.ForeignKey(
        'catalog.CostItem',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='deal_additional_option_lines',
    )
    name_snapshot = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=LineKind.choices, default=LineKind.MATERIAL)
    is_included = models.BooleanField(default=False)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    unit_snapshot = models.CharField(max_length=20, default='pcs', blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return f'{self.project_version} · {self.name_snapshot}'

    @property
    def line_total(self) -> Decimal:
        if not self.is_included:
            return Decimal('0')
        q = Decimal(str(self.quantity))
        p = Decimal(str(self.unit_price))
        return (q * p).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def unit_ru(self) -> str:
        mapping = {
            'sqm': 'м2',
            'pcs': 'шт',
            'lm': 'м.п.',
            'rubles': 'руб',
            'complex': 'компл.',
        }
        return mapping.get(self.unit_snapshot or '', self.unit_snapshot or '—')


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


class ProjectFile(models.Model):
    class Source(models.TextChoices):
        CLIENT = 'client', 'Client'
        DESIGNER = 'designer', 'Designer'
        SALES = 'sales', 'Sales'
        SYSTEM = 'system', 'System'

    class Category(models.TextChoices):
        PHOTO = 'photo', 'Photo'
        PDF = 'pdf', 'PDF'
        DWG = 'dwg', 'DWG'
        OTHER = 'other', 'Other'

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name='project_files')
    project_version = models.ForeignKey(
        ProjectVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='project_files',
    )
    source = models.CharField(max_length=20, choices=Source.choices)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    relative_path = models.CharField(max_length=500)
    original_name = models.CharField(max_length=255)
    size_bytes = models.PositiveBigIntegerField(default=0)
    mime_type = models.CharField(max_length=150, blank=True)
    ext = models.CharField(max_length=20, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_project_files',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='archived_project_files',
    )

    class Meta:
        indexes = [
            models.Index(fields=['deal', 'source', 'is_archived', '-updated_at'], name='project_file_list_idx'),
        ]
        ordering = ['-updated_at']

    def __str__(self):
        return self.original_name

    @property
    def absolute_path(self) -> Path:
        from .services.storage_paths import get_files_root

        return get_files_root() / self.relative_path
