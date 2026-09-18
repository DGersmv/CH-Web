from django import forms
from django.core.exceptions import ValidationError

from .models import (
    PORTAL_LOGIN_ID_MAX_LEN,
    PORTAL_LOGIN_ID_MIN_LEN,
    Client,
)


class ClientForm(forms.ModelForm):
    portal_password = forms.CharField(
        label='Пароль для входа',
        required=False,
        min_length=6,
        widget=forms.PasswordInput(
            attrs={'class': 'form-control', 'autocomplete': 'new-password', 'placeholder': 'Минимум 6 символов'},
            render_value=False,
        ),
        help_text='Вместе с ID для входа выдайте заказчику лично, не по email. Оставьте пустым, чтобы не менять текущий пароль.',
    )
    portal_password_confirm = forms.CharField(
        label='Повтор пароля',
        required=False,
        widget=forms.PasswordInput(
            attrs={'class': 'form-control', 'autocomplete': 'new-password'},
            render_value=False,
        ),
    )

    class Meta:
        model = Client
        fields = (
            'company_name',
            'last_name',
            'first_name',
            'middle_name',
            'phone',
            'email',
            'portal_login_id',
            'notes',
        )
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'organization'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'family-name'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'given-name'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'additional-name'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
            'portal_login_id': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'inputmode': 'numeric',
                    'autocomplete': 'off',
                    'placeholder': 'Например 100013',
                }
            ),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }
        labels = {
            'company_name': 'Название компании',
            'last_name': 'Фамилия',
            'first_name': 'Имя',
            'middle_name': 'Отчество',
            'phone': 'Телефон',
            'email': 'Email (не для входа в кабинет)',
            'portal_login_id': 'ID для входа',
            'notes': 'Заметки',
        }
        help_texts = {
            'email': 'Почту заказчику не отправляем. В кабинет: ID для входа + пароль, без OTP.',
            'portal_login_id': 'Отдельный номер кабинета, не внутренний № карточки. Пустое поле — назначить автоматически.',
        }

    def clean_portal_login_id(self):
        value = (self.cleaned_data.get('portal_login_id') or '').strip()
        if not value:
            if self.instance.pk:
                return (self.instance.portal_login_id or '').strip()
            return ''
        if not value.isdigit() or not (PORTAL_LOGIN_ID_MIN_LEN <= len(value) <= PORTAL_LOGIN_ID_MAX_LEN):
            raise ValidationError('ID для входа — от 4 до 12 цифр, без пробелов и букв.')
        qs = Client.objects.filter(portal_login_id=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('Такой ID для входа уже занят.')
        return value

    def clean(self):
        cleaned = super().clean()
        company = (cleaned.get('company_name') or '').strip()
        last = (cleaned.get('last_name') or '').strip()
        first = (cleaned.get('first_name') or '').strip()
        if not company and not (last and first):
            raise ValidationError(
                'Укажите название компании или заполните фамилию и имя (отчество по желанию).'
            )
        password = (cleaned.get('portal_password') or '').strip()
        confirm = (cleaned.get('portal_password_confirm') or '').strip()
        if password or confirm:
            if password != confirm:
                self.add_error('portal_password_confirm', 'Пароли не совпадают.')
            elif len(password) < 6:
                self.add_error('portal_password', 'Пароль — минимум 6 символов.')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw_password = (self.cleaned_data.get('portal_password') or '').strip()
        if raw_password:
            instance.set_portal_password(raw_password)
        if commit:
            instance.save()
            self.save_m2m()
        return instance
