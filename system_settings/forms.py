from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model

from catalog.forms import CostItemOptionForm
from catalog.forms import COST_ITEM_UNIT_CHOICES_RU
from catalog.models import CostItem
from system_settings.models import SystemConfig


class SystemConfigForm(forms.Form):
    default_margin_percent = forms.DecimalField(
        label='Маржа по умолчанию, %',
        min_value=Decimal('0'),
        max_digits=5,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={'class': 'form-control', 'step': '0.01', 'min': '0'},
        ),
    )
    stale_deal_days = forms.IntegerField(
        label='Сколько дней считать сделку неактивной',
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
    )
    task_reminder_hours = forms.IntegerField(
        label='Напоминать о просрочке задач через N часов',
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
    )


class IntegrationTokenCreateForm(forms.Form):
    name = forms.CharField(
        label='Название токена',
        max_length=120,
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'ArchiCAD plugin'},
        ),
    )
    owner = forms.ModelChoiceField(
        label='От имени пользователя',
        queryset=get_user_model().objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['owner'].queryset = get_user_model().objects.filter(
            is_active=True,
        ).order_by('username')


class CatalogItemForm(forms.ModelForm):
    class Meta:
        model = CostItem
        fields = [
            'code',
            'name_ru',
            'section',
            'category',
            'kind',
            'unit',
            'price_material',
            'price_work',
            'formula_multiplier',
            'default_included',
            'is_active',
            'sort_order',
        ]
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'name_ru': forms.TextInput(attrs={'class': 'form-control'}),
            'section': forms.Select(attrs={'class': 'form-select'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'kind': forms.Select(attrs={'class': 'form-select'}),
            'unit': forms.Select(attrs={'class': 'form-select'}),
            'price_material': forms.NumberInput(
                attrs={'class': 'form-control', 'step': '0.01', 'min': '0'},
            ),
            'price_work': forms.NumberInput(
                attrs={'class': 'form-control', 'step': '0.01', 'min': '0'},
            ),
            'formula_multiplier': forms.TextInput(attrs={'class': 'form-control'}),
            'default_included': forms.CheckboxInput(
                attrs={'class': 'form-check-input'},
            ),
            'is_active': forms.CheckboxInput(
                attrs={'class': 'form-check-input'},
            ),
            'sort_order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }


class CatalogOptionAdminForm(CostItemOptionForm):
    class Meta(CostItemOptionForm.Meta):
        fields = (
            'code',
            'name_ru',
            'manufacturer',
            'article',
            'country',
            'unit',
            'price',
            'description',
            'sort_order',
            'is_active',
            'is_default',
        )
        labels = {
            'code': 'Код',
            'name_ru': 'Наименование',
            'manufacturer': 'Производитель',
            'article': 'Артикул',
            'country': 'Страна',
            'unit': 'Ед. расчёта',
            'price': 'Цена, ₽',
            'description': 'Примечания',
            'sort_order': 'Порядок',
            'is_active': 'Активна',
            'is_default': 'По умолчанию',
        }
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'name_ru': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'manufacturer': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'article': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'country': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'unit': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'price': forms.NumberInput(
                attrs={'class': 'form-control form-control-sm', 'step': '0.01', 'min': '0'},
            ),
            'description': forms.Textarea(
                attrs={'class': 'form-control form-control-sm', 'rows': 2},
            ),
            'sort_order': forms.NumberInput(
                attrs={'class': 'form-control form-control-sm', 'min': '0'},
            ),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['unit'].choices = [('', 'Как в карточке позиции')] + list(
            COST_ITEM_UNIT_CHOICES_RU,
        )


SYSTEM_CONFIG_LABELS = {
    SystemConfig.Key.DEFAULT_MARGIN_PERCENT: 'Маржа по умолчанию',
    SystemConfig.Key.STALE_DEAL_DAYS: 'Порог неактивной сделки',
    SystemConfig.Key.TASK_REMINDER_HOURS: 'Горизонт напоминаний по задачам',
}
