from decimal import Decimal, InvalidOperation

from django import forms
from django.forms import inlineformset_factory
from django.contrib.auth import get_user_model
from django.utils import timezone

from clients.models import Client

from catalog.models import CostItemOption

from .models import (
    Deal,
    DealAdditionalOptionLine,
    DealBathroom,
    DealBathroomLine,
    ProjectVersion,
    ServiceRequest,
    build_project_code_from_parts,
    normalize_project_code,
)


class OptionWithPriceSelect(forms.Select):
    """Select модели с data-price / data-unit для подстановки цены в строке санузла."""

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs)
        self.price_map = {}
        self.unit_map = {}
        self.manufacturer_map = {}
        self.article_map = {}
        self.country_map = {}
        self.description_map = {}

    def attach_option_meta(self, queryset):
        self.price_map = {str(o.pk): str(o.price) for o in queryset}
        self.unit_map = {str(o.pk): (getattr(o, 'unit', '') or '') for o in queryset}
        self.manufacturer_map = {str(o.pk): (o.manufacturer or '') for o in queryset}
        self.article_map = {str(o.pk): (o.article or '') for o in queryset}
        self.country_map = {str(o.pk): (o.country or '') for o in queryset}
        self.description_map = {str(o.pk): (o.description or '') for o in queryset}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opt = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        raw_value = getattr(value, 'value', value)
        if raw_value not in (None, ''):
            key = str(raw_value)
            attrs_dict = opt.setdefault('attrs', {})
            if key in self.price_map:
                attrs_dict['data-price'] = self.price_map[key]
            if key in self.unit_map:
                attrs_dict['data-unit'] = self.unit_map[key]
            if key in self.manufacturer_map:
                attrs_dict['data-manufacturer'] = self.manufacturer_map[key]
            if key in self.article_map:
                attrs_dict['data-article'] = self.article_map[key]
            if key in self.country_map:
                attrs_dict['data-country'] = self.country_map[key]
            if key in self.description_map:
                attrs_dict['data-description'] = self.description_map[key]
        return opt


class DealCreateForm(forms.ModelForm):
    new_client_name = forms.CharField(
        required=False,
        label='Новый клиент (если нет в списке)',
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'Напр. Иванов Иван Иванович или ООО «Ромашка»'}
        ),
    )

    class Meta:
        model = Deal
        fields = [
            'module_count',
            'code_client_name',
            'code_site_name',
            'project_code',
            'client',
        ]
        widgets = {
            'module_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 15}),
            'code_client_name': forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'Напр. Иван или ООО «Ромашка»',
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
        }
        labels = {
            'module_count': 'Количество модулей',
            'code_client_name': 'Имя или название компании',
            'code_site_name': 'Название участка',
            'project_code': 'Код проекта',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].required = False
        self.fields['project_code'].required = False
        self.fields['client'].queryset = Client.objects.order_by('company_name', 'last_name', 'first_name', 'middle_name')

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
            self.add_error('code_client_name', 'Укажите имя или название компании.')
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
            self.add_error('project_code', 'Код должен содержать «МД» (например 3МД-Иван-Пулково).')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.code_client_name = (self.cleaned_data.get('code_client_name') or '').strip()
        instance.code_site_name = (self.cleaned_data.get('code_site_name') or '').strip()
        if commit:
            instance.save()
        return instance


class DealConfiguratorForm(forms.Form):
    class ConfigDecimalField(forms.DecimalField):
        def to_python(self, value):
            if value in self.empty_values:
                return super().to_python(value)
            raw = str(value).strip()
            raw = (
                raw.replace(' ', '')
                .replace('\xa0', '')
                .replace('\u202f', '')
                .replace('₽', '')
            )
            has_comma = ',' in raw
            has_dot = '.' in raw
            if has_comma and has_dot:
                last_comma = raw.rfind(',')
                last_dot = raw.rfind('.')
                dec_sep = ',' if last_comma > last_dot else '.'
                grp_sep = '.' if dec_sep == ',' else ','
                raw = raw.replace(grp_sep, '')
                if dec_sep == ',':
                    raw = raw.replace(',', '.')
            elif has_comma:
                raw = raw.replace(',', '.')
            return super().to_python(raw)

    building_area = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D3 Площадь застройки дома, кв.м')
    living_area = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D4 Жилая площадь дома, кв.м')
    ceiling_height = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=5, label='D5 Высота чистового потолка, м')
    floor_150_qty = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D7 Утепление пола 150мм, кв.м')
    floor_200_qty = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D8 Утепление пола 200мм, кв.м')
    floor_250_qty = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D9 Утепление пола 250мм, кв.м')
    floor_laminate_qty = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D10 Чистовое покрытие пола - ламинат, кв.м')
    floor_tile_qty = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D11 Чистовое покрытие пола - керамогранит, кв.м')
    facade_planken_lm = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D13 Наружный фасад планкен, м.п.')
    facade_combined_lm = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D14 Наружный фасад комбинированный, м.п.')
    partition_double_lm = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D17 Сдвоенные перегородки 200мм, м.п.')
    partition_single_lm = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D18 Одинарные перегородки 100мм, м.п.')
    finish_quarter_lm = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D20 Интерьерная доска "в четверть", м.п.')
    finish_ldsp_lm = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D21 Отделка ЛДСП, м.п.')
    finish_gkl_lm = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D22 Отделка ГКЛ, м.п.')
    finish_mdf_lm = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D23 Отделка МДФ, м.п.')
    finish_plywood_lm = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D24 Отделка Фанера/рейка, м.п.')
    bathroom_tile_lm = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D25 Отделка стен санузла керамогранитом, м.п.')
    roof_gable_qty = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D27 Кровля двускатная, кв.м')
    roof_flat_qty = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D28 Кровля плоская, кв.м')
    interior_doors_count = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D30 Двери межкомнатные, шт')
    sauna_cost = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=12, label='D31 Сауна, руб', required=False)
    sauna_installation_cost = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=12, label='D32 Монтаж сауны/печи, руб', required=False)
    windows_count = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D33 Окна, шт')
    windows_total_cost = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=12, label='D34 Стоимость окон, руб', required=False)
    panoramic_sections_count = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D35 Панорамные секции, шт')
    panoramic_sections_total_cost = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=12, label='D36 Стоимость панорамных секций, руб', required=False)
    bathrooms_count = ConfigDecimalField(min_value=0, decimal_places=2, max_digits=10, label='D37 Количество санузлов, шт')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            css = 'form-select' if isinstance(field, forms.ChoiceField) else 'form-control'
            field.widget.attrs.update({'class': css})
            if isinstance(field, forms.DecimalField):
                field.widget = forms.TextInput(
                    attrs={
                        'class': css,
                        'inputmode': 'decimal',
                        'autocomplete': 'off',
                        'data-format-thousands': '1',
                    }
                )


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
    portal_password = forms.CharField(
        label='Пароль для входа клиента',
        required=True,
        min_length=6,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Минимум 6 символов'}),
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

    def clean(self):
        cleaned = super().clean()
        email = (cleaned.get('email') or '').strip().lower()
        if not email:
            self.add_error('email', 'Для входа клиента укажите email.')
        return cleaned


class DealBathroomLineForm(forms.ModelForm):
    selected_option = forms.ModelChoiceField(
        queryset=CostItemOption.objects.none(),
        required=False,
        label='Модель',
        widget=OptionWithPriceSelect(
            attrs={'class': 'form-select form-select-sm bathroom-option-select'},
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = getattr(self, 'instance', None)
        if instance and instance.cost_item_id and instance.kind == DealBathroomLine.LineKind.MATERIAL:
            qs = instance.cost_item.options.filter(is_active=True).order_by('sort_order', 'name_ru')
            self.fields['selected_option'].queryset = qs
            self.fields['selected_option'].widget.attach_option_meta(qs)
            self.fields['selected_option'].label_from_instance = lambda o: o.name_ru
            if qs.exists():
                self.fields['selected_option'].empty_label = None
            if instance.pk and not instance.selected_option_id:
                first_opt = qs.exclude(code='customer_material').order_by('sort_order', 'id').first()
                if first_opt is not None:
                    self.initial['selected_option'] = first_opt.pk
        else:
            self.fields['selected_option'].queryset = CostItemOption.objects.none()

    @staticmethod
    def _to_decimal(value, field_name):
        raw = '' if value is None else str(value).strip()
        raw = (
            raw.replace(' ', '')
            .replace('\xa0', '')
            .replace('\u202f', '')
            .replace('₽', '')
        )
        if raw == '':
            raise forms.ValidationError(f'Поле "{field_name}" обязательно для заполнения.')
        # Поддерживаем форматы:
        # - 12000.50
        # - 12,000.50
        # - 12 000,50
        # - 12000,50
        has_comma = ',' in raw
        has_dot = '.' in raw
        if has_comma and has_dot:
            # Последний разделитель считаем десятичным, остальные удаляем как группировочные.
            last_comma = raw.rfind(',')
            last_dot = raw.rfind('.')
            dec_sep = ',' if last_comma > last_dot else '.'
            grp_sep = '.' if dec_sep == ',' else ','
            raw = raw.replace(grp_sep, '')
            if dec_sep == ',':
                raw = raw.replace(',', '.')
        elif has_comma:
            raw = raw.replace(',', '.')
        try:
            dec = Decimal(raw)
        except (InvalidOperation, ValueError, TypeError):
            raise forms.ValidationError(f'Поле "{field_name}" должно быть числом.')
        if dec < 0:
            raise forms.ValidationError(f'Поле "{field_name}" не может быть отрицательным.')
        return dec

    def clean_quantity(self):
        return self._to_decimal(self.data.get(self.add_prefix('quantity')), 'Кол-во')

    def clean_unit_price(self):
        return self._to_decimal(self.data.get(self.add_prefix('unit_price')), 'Цена')

    class Meta:
        model = DealBathroomLine
        fields = ('is_included', 'selected_option', 'quantity', 'unit_price')
        widgets = {
            'is_included': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'step': '0.01', 'min': '0'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'step': '0.01', 'min': '0'}),
        }


BathroomLineFormSet = inlineformset_factory(
    DealBathroom,
    DealBathroomLine,
    form=DealBathroomLineForm,
    extra=0,
    can_delete=False,
)


class DealAdditionalOptionLineForm(forms.ModelForm):
    class Meta:
        model = DealAdditionalOptionLine
        fields = ('is_included', 'quantity', 'unit_price')
        widgets = {
            'is_included': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'step': '0.01', 'min': '0'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'step': '0.01', 'min': '0'}),
        }


class AdditionalOptionCreateForm(forms.Form):
    UNIT_CHOICES = [
        ('sqm', 'м2'),
        ('pcs', 'шт'),
        ('lm', 'м.п.'),
        ('rubles', 'руб'),
        ('complex', 'компл.'),
    ]
    name = forms.CharField(max_length=255, label='Наименование')
    unit = forms.ChoiceField(choices=UNIT_CHOICES, label='Ед.')
    quantity = forms.DecimalField(min_value=0, decimal_places=2, max_digits=12, label='Кол-во')
    unit_price = forms.DecimalField(min_value=0, decimal_places=2, max_digits=12, label='Цена, ₽')
    is_included = forms.BooleanField(required=False, initial=True, label='Вкл.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs.update({'class': 'form-control form-control-sm'})
        self.fields['unit'].widget.attrs.update({'class': 'form-select form-select-sm'})
        self.fields['quantity'].widget.attrs.update({'class': 'form-control form-control-sm', 'step': '0.01', 'min': '0'})
        self.fields['unit_price'].widget.attrs.update({'class': 'form-control form-control-sm', 'step': '0.01', 'min': '0'})
        self.fields['is_included'].widget.attrs.update({'class': 'form-check-input'})


AdditionalOptionLineFormSet = inlineformset_factory(
    ProjectVersion,
    DealAdditionalOptionLine,
    form=DealAdditionalOptionLineForm,
    extra=0,
    can_delete=False,
)


class ServiceRequestForm(forms.ModelForm):
    """Заведение / редактирование обращения в сервис."""

    class Meta:
        model = ServiceRequest
        fields = [
            'kind',
            'priority',
            'source',
            'title',
            'description',
            'deal',
            'client',
            'reporter_name',
            'reporter_phone',
            'assignee',
        ]
        widgets = {
            'kind': forms.Select(attrs={'class': 'form-select'}),
            'priority': forms.Select(attrs={'class': 'form-select'}),
            'source': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off',
                                            'placeholder': 'Напр. Скрипит пол в спальне'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4,
                                                 'placeholder': 'Что случилось, где, когда заметили'}),
            'deal': forms.Select(attrs={'class': 'form-select'}),
            'client': forms.Select(attrs={'class': 'form-select'}),
            'reporter_name': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
            'reporter_phone': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off',
                                                     'placeholder': '+7'}),
            'assignee': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['deal'].required = False
        self.fields['client'].required = False
        self.fields['assignee'].required = False
        self.fields['description'].required = False
        self.fields['reporter_name'].required = False
        self.fields['reporter_phone'].required = False
        self.fields['deal'].queryset = Deal.objects.select_related('client').order_by('-updated_at')
        self.fields['client'].queryset = Client.objects.order_by(
            'company_name', 'last_name', 'first_name', 'middle_name'
        )
        self.fields['assignee'].queryset = get_user_model().objects.filter(is_active=True).order_by('username')
        self.fields['deal'].empty_label = '— не привязано —'
        self.fields['client'].empty_label = '— не выбран —'
        self.fields['assignee'].empty_label = '— не назначен —'


class ServiceRequestCommentForm(forms.Form):
    text = forms.CharField(
        label='Комментарий',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2,
                                     'placeholder': 'Что сделано / договорённости'}),
    )


class DealFileUploadForm(forms.Form):
    source = forms.ChoiceField(
        choices=(('client', 'От заказчика'), ('designer', 'От проектировщика'), ('sales', 'От отдела продаж')),
        widget=forms.HiddenInput(),
    )
    upload = forms.FileField(
        label='Файл',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control form-control-sm'}),
    )
