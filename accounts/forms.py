from django import forms
from django.contrib.auth import get_user_model


class EmployeeCreateForm(forms.ModelForm):
    password = forms.CharField(label='Пароль', widget=forms.PasswordInput(attrs={'class': 'form-control form-control-sm'}))

    class Meta:
        model = get_user_model()
        fields = ['username', 'first_name', 'last_name', 'email', 'role', 'is_active']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'email': forms.EmailInput(attrs={'class': 'form-control form-control-sm'}),
            'role': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user


class EmployeeUpdateForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ['role', 'is_active']
        widgets = {
            'role': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class DashboardMessageForm(forms.Form):
    recipient = forms.ModelChoiceField(
        queryset=get_user_model().objects.none(),
        label='Кому',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
    body = forms.CharField(
        label='Сообщение',
        widget=forms.Textarea(attrs={'class': 'form-control form-control-sm', 'rows': 2, 'placeholder': 'Введите сообщение'}),
    )
    attachment = forms.FileField(
        required=False,
        label='Файл',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control form-control-sm'}),
    )

    def __init__(self, *args, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = get_user_model().objects.filter(is_active=True)
        if current_user is not None and getattr(current_user, 'pk', None):
            queryset = queryset.exclude(pk=current_user.pk)
        self.fields['recipient'].queryset = queryset.order_by('first_name', 'last_name', 'username')
        self.fields['recipient'].label_from_instance = self._user_label

    @staticmethod
    def _user_label(user):
        full_name = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip()
        return full_name or user.username

    def clean(self):
        cleaned_data = super().clean()
        body = (cleaned_data.get('body') or '').strip()
        attachment = cleaned_data.get('attachment')
        if not body and not attachment:
            raise forms.ValidationError('Добавьте текст сообщения или прикрепите файл.')
        return cleaned_data
