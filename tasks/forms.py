from django import forms

from .models import Task


class DealTaskCreateForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['title', 'due_date', 'assignee']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Название задачи'}),
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'assignee': forms.Select(attrs={'class': 'form-select'}),
        }
