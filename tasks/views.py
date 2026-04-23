from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods, require_POST
from django.views.generic import TemplateView

from deals.models import Deal

from .forms import DealTaskCreateForm
from .models import Task


class TaskListView(LoginRequiredMixin, TemplateView):
    template_name = 'task_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        base = Task.objects.select_related('deal', 'assignee').filter(assignee=user).order_by('due_date', 'created_at')
        context['open_tasks'] = base.filter(is_done=False)
        context['done_tasks'] = base.filter(is_done=True).order_by('-completed_at')
        return context


@login_required
@require_POST
def toggle_task(request, task_id):
    task = get_object_or_404(Task.objects.select_related('deal', 'assignee'), pk=task_id)
    if task.assignee and task.assignee != request.user and not request.user.is_superuser:
        return HttpResponseForbidden('Not allowed')
    if not task.is_done:
        task.mark_done()
    return render(
        request,
        'includes/task_row.html',
        {
            'task': task,
            'show_deal': request.GET.get('show_deal') == '1',
            'compact': request.GET.get('compact') == '1',
        },
    )


@login_required
@require_http_methods(['GET', 'POST'])
def create_task_for_deal(request, deal_id):
    deal = get_object_or_404(Deal, pk=deal_id)
    assignee_queryset = request.user.__class__.objects.filter(role='manager').order_by('username')
    if request.method == 'POST':
        form = DealTaskCreateForm(request.POST)
        form.fields['assignee'].queryset = assignee_queryset
        if form.is_valid():
            task = form.save(commit=False)
            task.deal = deal
            if task.assignee is None:
                task.assignee = request.user
            task.save()
            tasks_for_deal = deal.tasks.select_related('assignee').order_by('is_done', 'due_date')
            response = render(
                request,
                'includes/deal_tasks_block.html',
                {'deal': deal, 'tasks_for_deal': tasks_for_deal},
            )
            response['HX-Trigger'] = 'taskCreated'
            return response
        return render(
            request,
            'includes/task_create_form.html',
            {'deal': deal, 'form': form},
            status=400,
        )

    form = DealTaskCreateForm(initial={'assignee': request.user, 'due_date': request.GET.get('due_date')})
    form.fields['assignee'].queryset = assignee_queryset
    return render(
        request,
        'includes/task_create_form.html',
        {'deal': deal, 'form': form},
    )
