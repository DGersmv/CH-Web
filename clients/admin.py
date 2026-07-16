from django.contrib import admin
from django import forms

from .models import Client


class ClientAdminForm(forms.ModelForm):
    portal_password = forms.CharField(
        label='Пароль для входа клиента',
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text='Оставьте пустым, чтобы не менять текущий пароль.',
    )

    class Meta:
        model = Client
        fields = '__all__'

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw_password = (self.cleaned_data.get('portal_password') or '').strip()
        if raw_password:
            instance.set_portal_password(raw_password)
        if commit:
            instance.save()
            self.save_m2m()
        return instance


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    form = ClientAdminForm
    list_display = ('full_name_display', 'phone', 'email', 'created_at', 'created_by')
    search_fields = ('last_name', 'first_name', 'middle_name', 'company_name', 'phone', 'email', 'notes')
    list_filter = ('created_at',)
    ordering = ('company_name', 'last_name', 'first_name', 'middle_name')
    fields = (
        'company_name',
        'last_name',
        'first_name',
        'middle_name',
        'phone',
        'email',
        'portal_password',
        'notes',
        'created_by',
    )

    @admin.display(description='Клиент')
    def full_name_display(self, obj):
        return obj.full_name
