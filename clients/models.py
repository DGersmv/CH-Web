from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models

PORTAL_LOGIN_ID_BASE = 100000
PORTAL_LOGIN_ID_MIN_LEN = 4
PORTAL_LOGIN_ID_MAX_LEN = 12


def parse_quick_client_name(raw: str) -> dict:
    """Разбор строки из поля «новый клиент» в поля модели (без сохранения)."""
    s = (raw or '').strip()
    if not s:
        return {}
    upper = s.upper()
    if upper.startswith('ООО') or upper.startswith('ИП') or '«' in s or '"' in s[:24]:
        return {
            'company_name': s,
            'last_name': '',
            'first_name': '',
            'middle_name': '',
        }
    parts = s.split()
    if len(parts) == 1:
        return {
            'company_name': '',
            'last_name': parts[0],
            'first_name': '',
            'middle_name': '',
        }
    if len(parts) == 2:
        return {
            'company_name': '',
            'last_name': parts[0],
            'first_name': parts[1],
            'middle_name': '',
        }
    return {
        'company_name': '',
        'last_name': parts[0],
        'first_name': parts[1],
        'middle_name': ' '.join(parts[2:]),
    }


class Client(models.Model):
    company_name = models.CharField('Название компании', max_length=255, blank=True)
    last_name = models.CharField('Фамилия', max_length=100, blank=True)
    first_name = models.CharField('Имя', max_length=100, blank=True)
    middle_name = models.CharField('Отчество', max_length=100, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    portal_login_id = models.CharField(
        'ID для входа',
        max_length=PORTAL_LOGIN_ID_MAX_LEN,
        unique=True,
        blank=True,
        default='',
        help_text='Отдельный номер для кабинета, не внутренний № карточки.',
    )
    portal_password_hash = models.CharField(max_length=128, blank=True, default='')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_clients',
    )

    class Meta:
        ordering = ['company_name', 'last_name', 'first_name', 'middle_name']

    @property
    def full_name(self) -> str:
        if (self.company_name or '').strip():
            return (self.company_name or '').strip()
        parts = [
            (self.last_name or '').strip(),
            (self.first_name or '').strip(),
            (self.middle_name or '').strip(),
        ]
        return ' '.join(p for p in parts if p).strip()

    def __str__(self):
        label = self.full_name
        return label if label else f'Клиент #{self.pk}'

    @property
    def has_portal_password(self) -> bool:
        return bool(self.portal_password_hash)

    def assign_portal_login_id(self) -> bool:
        if self.pk is None:
            return False
        current = (self.portal_login_id or '').strip()
        if current:
            return False
        used = set(
            Client.objects.exclude(pk=self.pk)
            .exclude(portal_login_id='')
            .values_list('portal_login_id', flat=True)
        )
        candidate = str(PORTAL_LOGIN_ID_BASE + int(self.pk))
        while candidate in used:
            candidate = str(int(candidate) + 1)
        self.portal_login_id = candidate
        return True

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.assign_portal_login_id():
            super().save(update_fields=['portal_login_id'])

    def set_portal_password(self, raw_password: str) -> None:
        raw = (raw_password or '').strip()
        self.portal_password_hash = make_password(raw) if raw else ''

    def check_portal_password(self, raw_password: str) -> bool:
        if not self.portal_password_hash:
            return False
        return check_password(raw_password or '', self.portal_password_hash)
