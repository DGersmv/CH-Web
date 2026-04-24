from django import forms

from deals.models import ProjectFile
from .models import Task


class DealTaskCreateForm(forms.ModelForm):
    project_file = forms.ModelChoiceField(
        queryset=ProjectFile.objects.none(),
        required=False,
        empty_label='Не выбрано',
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Файл из сделки',
    )

    class Meta:
        model = Task
        fields = ['title', 'description', 'due_date', 'assignee', 'attachment', 'project_file']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Название задачи'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Описание задачи'}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'assignee': forms.Select(attrs={'class': 'form-select'}),
            'attachment': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assignee'].label_from_instance = self._assignee_label

    @staticmethod
    def _assignee_label(user):
        full_name = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip()
        return full_name or user.username
