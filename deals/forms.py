from django import forms
from django.contrib.auth import get_user_model

from clients.models import Client

from .models import Deal, normalize_project_code


class DealCreateForm(forms.ModelForm):
    new_client_name = forms.CharField(
        required=False,
        label='Новый клиент (если нет в списке)',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ФИО или название клиента'}),
    )

    class Meta:
        model = Deal
        fields = ['project_code', 'module_count', 'client', 'assigned_manager']
        widgets = {
            'project_code': forms.TextInput(attrs={'class': 'form-control'}),
            'module_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 15}),
            'client': forms.Select(attrs={'class': 'form-select'}),
            'assigned_manager': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].required = False
        self.fields['assigned_manager'].required = False
        self.fields['client'].queryset = Client.objects.order_by('full_name')
        self.fields['assigned_manager'].queryset = get_user_model().objects.filter(role='manager').order_by('username')

    def clean_project_code(self):
        value = self.cleaned_data['project_code'].strip()
        normalized = normalize_project_code(value)
        if Deal.objects.filter(project_code_normalized=normalized).exists():
            raise forms.ValidationError('Сделка с таким project_code уже существует.')
        if 'мд' not in normalized:
            raise forms.ValidationError('Формат project_code должен включать "МД".')
        return value


class DealConfiguratorForm(forms.Form):
    building_area = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D3 Площадь застройки дома, кв.м')
    living_area = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D4 Жилая площадь дома, кв.м')
    ceiling_height = forms.DecimalField(min_value=0, decimal_places=2, max_digits=5, label='D5 Высота чистового потолка, м')
    floor_150_qty = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D7 Утепление пола 150мм, кв.м')
    floor_200_qty = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D8 Утепление пола 200мм, кв.м')
    floor_250_qty = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D9 Утепление пола 250мм, кв.м')
    floor_laminate_qty = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D10 Чистовое покрытие пола - ламинат, кв.м')
    floor_tile_qty = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D11 Чистовое покрытие пола - керамогранит, кв.м')
    facade_planken_lm = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D13 Наружный фасад планкен, м.п.')
    facade_combined_lm = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D14 Наружный фасад комбинированный, м.п.')
    partition_double_lm = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D17 Сдвоенные перегородки 200мм, м.п.')
    partition_single_lm = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D18 Одинарные перегородки 100мм, м.п.')
    finish_quarter_lm = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D20 Интерьерная доска "в четверть", м.п.')
    finish_ldsp_lm = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D21 Отделка ЛДСП, м.п.')
    finish_gkl_lm = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D22 Отделка ГКЛ, м.п.')
    finish_mdf_lm = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D23 Отделка МДФ, м.п.')
    finish_plywood_lm = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D24 Отделка Фанера/рейка, м.п.')
    bathroom_tile_lm = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D25 Отделка стен санузла керамогранитом, м.п.')
    roof_gable_qty = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D27 Кровля двускатная, кв.м')
    roof_flat_qty = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D28 Кровля плоская, кв.м')
    interior_doors_count = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D30 Двери межкомнатные, шт')
    sauna_cost = forms.DecimalField(min_value=0, decimal_places=2, max_digits=12, label='D31 Сауна, руб', required=False)
    sauna_installation_cost = forms.DecimalField(min_value=0, decimal_places=2, max_digits=12, label='D32 Монтаж сауны/печи, руб', required=False)
    windows_count = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D33 Окна, шт')
    windows_total_cost = forms.DecimalField(min_value=0, decimal_places=2, max_digits=12, label='D34 Стоимость окон, руб', required=False)
    panoramic_sections_count = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D35 Панорамные секции, шт')
    panoramic_sections_total_cost = forms.DecimalField(min_value=0, decimal_places=2, max_digits=12, label='D36 Стоимость панорамных секций, руб', required=False)
    bathrooms_count = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='D37 Количество санузлов, шт')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            css = 'form-select' if isinstance(field, forms.ChoiceField) else 'form-control'
            field.widget.attrs.update({'class': css})
