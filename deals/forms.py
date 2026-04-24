from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from clients.models import Client

from .models import Deal, build_project_code_from_parts, normalize_project_code


class DealCreateForm(forms.ModelForm):
    new_client_name = forms.CharField(
        required=False,
        label='Новый клиент (если нет в списке)',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ФИО или название клиента'}),
    )

    class Meta:
        model = Deal
        fields = [
            'module_count',
            'code_client_name',
            'code_site_name',
            'project_code',
            'client',
            'assigned_manager',
        ]
        widgets = {
            'module_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 15}),
            'code_client_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Напр. Иванов или ООО «Ромашка»',
                    'autocomplete': 'off',
                }
            ),
            'code_site_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Напр. Пулково',
                    'autocomplete': 'off',
                }
            ),
            'project_code': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
            'client': forms.Select(attrs={'class': 'form-select'}),
            'assigned_manager': forms.Select(attrs={'class': 'form-select'}),
        }
        labels = {
            'module_count': 'Количество модулей',
            'code_client_name': 'Фамилия или название компании',
            'code_site_name': 'Название участка',
            'project_code': 'Код проекта',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].required = False
        self.fields['assigned_manager'].required = False
        self.fields['project_code'].required = False
        self.fields['client'].queryset = Client.objects.order_by('full_name')
        self.fields['assigned_manager'].queryset = get_user_model().objects.filter(role='manager').order_by('username')

    def clean(self):
        cleaned = super().clean()
        if 'module_count' in self.errors:
            return cleaned

        module_count = cleaned.get('module_count')
        if module_count is None:
            return cleaned

        client_part = (cleaned.get('code_client_name') or '').strip()
        site_part = (cleaned.get('code_site_name') or '').strip()
        if not client_part:
            self.add_error('code_client_name', 'Укажите фамилию или название компании.')
        if not site_part:
            self.add_error('code_site_name', 'Укажите название участка.')
        if 'code_client_name' in self.errors or 'code_site_name' in self.errors:
            return cleaned

        project_code = (cleaned.get('project_code') or '').strip()
        if not project_code:
            project_code = build_project_code_from_parts(module_count, client_part, site_part)
        cleaned['project_code'] = project_code

        norm = normalize_project_code(cleaned['project_code'])
        if Deal.objects.filter(project_code_normalized=norm).exists():
            self.add_error('project_code', 'Сделка с таким кодом проекта уже существует.')
        elif 'мд' not in norm:
            self.add_error('project_code', 'Код должен содержать «МД» (например 3МД-Иванов-Пулково).')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.code_client_name = (self.cleaned_data.get('code_client_name') or '').strip()
        instance.code_site_name = (self.cleaned_data.get('code_site_name') or '').strip()
        if commit:
            instance.save()
        return instance


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


class DashboardLeadForm(forms.Form):
    module_count = forms.IntegerField(
        label='Количество модулей',
        min_value=0,
        max_value=15,
        initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 15}),
    )
    last_name = forms.CharField(
        label='Фамилия',
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
    )
    first_name = forms.CharField(
        label='Имя',
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
    )
    middle_name = forms.CharField(
        label='Отчество',
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
    )
    phone = forms.CharField(
        label='Номер телефона',
        initial='+7',
        required=False,
        max_length=50,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+7'}),
    )
    email = forms.EmailField(
        label='Адрес электронной почты',
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'client@example.com'}),
    )
    location = forms.CharField(
        label='Участок (где планируется строительство)',
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
    )
    region_or_city = forms.CharField(
        label='Область или город',
        required=False,
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
    )
    street = forms.CharField(
        label='Улица',
        required=False,
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
    )
    house_number = forms.CharField(
        label='Номер дома',
        required=False,
        max_length=50,
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
    )
    comment = forms.CharField(
        label='Комментарий',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Что важно помнить при общении с клиентом'}),
    )
    mortgage_required = forms.BooleanField(
        label='Ипотека',
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    target_deal_date = forms.DateField(
        label='Срок выхода на сделку',
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        input_formats=['%Y-%m-%d'],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields['target_deal_date'].initial = timezone.localdate()

    def clean_phone(self):
        value = (self.cleaned_data.get('phone') or '').strip()
        if not value:
            return '+7'
        if not value.startswith('+7'):
            raise forms.ValidationError('Номер должен начинаться с +7.')
        return value


class DealFileUploadForm(forms.Form):
    source = forms.ChoiceField(
        choices=(('client', 'От заказчика'), ('designer', 'От проектировщика'), ('sales', 'От отдела продаж')),
        widget=forms.HiddenInput(),
    )
    upload = forms.FileField(
        label='Файл',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control form-control-sm'}),
    )
