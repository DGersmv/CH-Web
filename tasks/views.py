import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods, require_POST
from django.views.generic import TemplateView

from accounts.events import create_notification, log_audit_event
from deals.models import Deal, ProjectFile

from .forms import DealTaskCreateForm
from .models import Task


def _copy_project_file_to_task_attachment(task):
    if not task.project_file or task.attachment:
        return
    source_path = task.project_file.absolute_path
    if not source_path.exists() or not source_path.is_file():
        return

    media_root = Path(settings.MEDIA_ROOT)
    destination_dir = media_root / 'task_attachments'
    destination_dir.mkdir(parents=True, exist_ok=True)
    ext = source_path.suffix
    safe_stem = Path(task.project_file.original_name).stem or 'file'
    filename = f"task-{task.id}-{safe_stem}-{uuid.uuid4().hex[:8]}{ext}"
    destination_path = destination_dir / filename
    shutil.copy2(source_path, destination_path)
    task.attachment = f'task_attachments/{filename}'
    task.save(update_fields=['attachment'])


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
    if not task.is_done:
        task.mark_done()
        log_audit_event(
            actor=request.user,
            event_type='task.completed',
            entity_model='Task',
            entity_id=task.id,
            payload={'deal_id': task.deal_id},
            request=request,
        )
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
@require_http_methods(['GET'])
def open_task_file(request, task_id):
    task = get_object_or_404(Task.objects.select_related('project_file'), pk=task_id)
    if not task.attachment and task.project_file:
        _copy_project_file_to_task_attachment(task)

    if not task.attachment:
        raise Http404('Task file not found')

    file_path = Path(settings.MEDIA_ROOT) / task.attachment.name
    if not file_path.exists() or not file_path.is_file():
        raise Http404('Task file not found')

    return FileResponse(file_path.open('rb'), as_attachment=False, filename=file_path.name)


@login_required
@require_http_methods(['GET', 'POST'])
def create_task_for_deal(request, deal_id):
    deal = get_object_or_404(Deal, pk=deal_id)
    assignee_queryset = request.user.__class__.objects.filter(is_active=True).order_by('username')
    project_file_queryset = ProjectFile.objects.filter(deal=deal, is_archived=False).order_by('-created_at')
    if request.method == 'POST':
        form = DealTaskCreateForm(request.POST, request.FILES)
        form.fields['assignee'].queryset = assignee_queryset
        form.fields['project_file'].queryset = project_file_queryset
        if form.is_valid():
            task = form.save(commit=False)
            task.deal = deal
            if task.assignee is None:
                task.assignee = request.user
            task.save()
            _copy_project_file_to_task_attachment(task)
            if task.assignee_id:
                create_notification(
                    user=task.assignee,
                    actor=request.user,
                    notification_type='task_assigned',
                    title='Новая задача',
                    body=task.title,
                    related_model='Task',
                    related_id=task.id,
                )
            log_audit_event(
                actor=request.user,
                event_type='task.created',
                entity_model='Task',
                entity_id=task.id,
                payload={
                    'deal_id': deal.id,
                    'assignee_id': task.assignee_id,
                    'title': task.title,
                },
                request=request,
            )
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
    form.fields['project_file'].queryset = project_file_queryset
    return render(
        request,
        'includes/task_create_form.html',
        {'deal': deal, 'form': form},
    )
