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
    FLOOR_CHOICES = [
        ('150', 'Утепление пола 150мм'),
        ('200', 'Утепление пола 200мм'),
        ('250', 'Утепление пола 250мм'),
    ]
    ROOF_CHOICES = [
        ('gable', 'Кровля двускатная'),
        ('flat', 'Кровля плоская'),
    ]

    building_area = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='Площадь застройки, кв.м')
    living_area = forms.DecimalField(min_value=0, decimal_places=2, max_digits=10, label='Жилая площадь, кв.м')
    ceiling_height = forms.DecimalField(min_value=2, decimal_places=2, max_digits=4, label='Высота потолка, м')
    floor_insulation = forms.ChoiceField(choices=FLOOR_CHOICES, label='Утепление пола')
    roof_type = forms.ChoiceField(choices=ROOF_CHOICES, label='Тип кровли')
    windows_count = forms.IntegerField(min_value=0, label='Окна, шт')
    sauna_cost = forms.DecimalField(min_value=0, decimal_places=2, max_digits=12, label='Сауна, руб', required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            css = 'form-select' if isinstance(field, forms.ChoiceField) else 'form-control'
            field.widget.attrs.update({'class': css})
