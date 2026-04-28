from django import forms

from .models import CostItem, CostItemOption


# Для подписей в UI (значения совпадают с CostItem.Unit).
COST_ITEM_UNIT_CHOICES_RU = [
    ('sqm', 'м²'),
    ('lm', 'пог. м'),
    ('pcs', 'шт'),
    ('complex', 'комплект'),
    ('rubles', '₽'),
]


class CostItemOptionForm(forms.ModelForm):
    """Создание позиции модели из формы на странице санузла."""

    class Meta:
        model = CostItemOption
        fields = (
            'name_ru',
            'manufacturer',
            'article',
            'country',
            'unit',
            'price',
            'description',
        )
        labels = {
            'name_ru': 'Наименование',
            'manufacturer': 'Производитель',
            'article': 'Артикул',
            'country': 'Страна',
            'unit': 'Ед. расчёта',
            'price': 'Цена, ₽',
            'description': 'Примечания',
        }
        widgets = {
            'name_ru': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'manufacturer': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'article': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'country': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'unit': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'price': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'step': '0.01', 'min': '0'}),
            'description': forms.Textarea(attrs={'class': 'form-control form-control-sm', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['unit'].required = False
        self.fields['unit'].choices = [('', 'Как в карточке позиции')] + list(COST_ITEM_UNIT_CHOICES_RU)
