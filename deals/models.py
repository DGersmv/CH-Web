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
        verbose_name='Имя / компания (в коде проекта)',
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


class LibraryAsset(models.Model):
    class Section(models.TextChoices):
        LAYOUT = 'layout', 'Планировки'
        CONTRACT_TEMPLATE = 'contract_template', 'Шаблоны договоров'
        PHOTO = 'photo', 'Фото'
        VIDEO = 'video', 'Видео'
        SUPPLIER_FILE = 'supplier_file', 'Файлы поставщиков'

    class ModuleGroup(models.TextChoices):
        M1 = 'm1', '1 Модуль'
        M2 = 'm2', '2 Модуля'
        M3 = 'm3', '3 Модуля'
        M4 = 'm4', '4 Модуля'
        M5 = 'm5', '5 Модулей'
        M6PLUS = 'm6plus', '6+ Модулей'

    class SupplierCategory(models.TextChoices):
        FINISHING = 'finishing', 'Отделка'
        PLUMBING = 'plumbing', 'Сантехника'
        ELECTRICAL = 'electrical', 'Электрика'
        FLOOR_HEATING = 'floor_heating', 'Теплые полы'
        STOVES_FIREPLACES = 'stoves_fireplaces', 'Печи и Камины'
        WINDOWS = 'windows', 'Окна'
        FURNITURE = 'furniture', 'Мебель'

    section = models.CharField(max_length=20, choices=Section.choices)
    module_group = models.CharField(max_length=20, choices=ModuleGroup.choices)
    supplier_category = models.CharField(max_length=30, choices=SupplierCategory.choices, blank=True, default='')
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
        related_name='uploaded_library_assets',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['section', 'module_group', '-updated_at'], name='library_asset_list_idx'),
        ]
        ordering = ['-updated_at']

    def __str__(self):
        return self.original_name

    @property
    def absolute_path(self) -> Path:
        from .services.storage_paths import get_files_root

        return get_files_root() / self.relative_path


class DealClientPortalOtp(models.Model):
    """One-time code issued for a deal client portal login."""

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name='client_portal_otps')
    email = models.EmailField()
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempts_left = models.PositiveSmallIntegerField(default=5)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['deal', 'email', '-created_at'], name='deal_portal_otp_lookup_idx'),
            models.Index(fields=['expires_at'], name='deal_portal_otp_exp_idx'),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'OTP {self.deal_id} {self.email}'


class DealClientPortalSession(models.Model):
    """Session for a deal client portal, stored as hashed token."""

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name='client_portal_sessions')
    email = models.EmailField()
    session_token_hash = models.CharField(max_length=128, db_index=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['deal', 'email', '-created_at'], name='deal_portal_sess_lookup_idx'),
            models.Index(fields=['expires_at'], name='deal_portal_sess_exp_idx'),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'Session {self.deal_id} {self.email}'


class DealClientMessage(models.Model):
    class AuthorType(models.TextChoices):
        CLIENT = 'client', 'Client'
        STAFF = 'staff', 'Staff'

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name='client_messages')
    author_type = models.CharField(max_length=20, choices=AuthorType.choices)
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deal_client_messages',
    )
    author_email = models.EmailField(blank=True, default='')
    body = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['deal', '-created_at'], name='deal_client_msg_list_idx'),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.deal_id} {self.author_type} #{self.id}'


class DealClientMessageAttachment(models.Model):
    class Kind(models.TextChoices):
        PROJECT_FILE = 'project_file', 'Project file'
        VOICE = 'voice', 'Voice'

    message = models.ForeignKey(DealClientMessage, on_delete=models.CASCADE, related_name='attachments')
    kind = models.CharField(max_length=30, choices=Kind.choices)
    project_file = models.ForeignKey(
        ProjectFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='client_message_attachments',
    )
    mime_type = models.CharField(max_length=150, blank=True, default='')
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['message', 'kind'], name='deal_client_att_msg_kind_idx'),
        ]
        ordering = ['id']

    def __str__(self):
        return f'Attachment {self.kind} for msg {self.message_id}'
