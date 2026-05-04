from django import forms
from django.core.exceptions import ValidationError

from .models import Client


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ('company_name', 'last_name', 'first_name', 'middle_name', 'phone', 'email', 'notes')
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'organization'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'family-name'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'given-name'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'additional-name'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }
        labels = {
            'company_name': 'Название компании',
            'last_name': 'Фамилия',
            'first_name': 'Имя',
            'middle_name': 'Отчество',
            'phone': 'Телефон',
            'email': 'Email',
            'notes': 'Заметки',
        }

    def clean(self):
        cleaned = super().clean()
        company = (cleaned.get('company_name') or '').strip()
        last = (cleaned.get('last_name') or '').strip()
        first = (cleaned.get('first_name') or '').strip()
        if company:
            return cleaned
        if last and first:
            return cleaned
        raise ValidationError(
            'Укажите название компании или заполните фамилию и имя (отчество по желанию).'
        )
