"""Сервис / Рекламации: обращения клиентов после сдачи объекта."""

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import can_edit_deals
from system_settings.events import record_domain_event

from .forms import ServiceRequestCommentForm, ServiceRequestForm
from .models import ServiceRequest, ServiceRequestEvent


def _can_edit(request):
    return can_edit_deals(request.user)


@login_required
def service_list(request):
    status = request.GET.get('status')
    if status is None:
        status = 'open'
    status = status.strip()
    kind = (request.GET.get('kind') or '').strip()
    search = (request.GET.get('q') or '').strip()

    requests_qs = (
        ServiceRequest.objects.select_related('deal', 'deal__client', 'client', 'assignee')
        .order_by('-created_at')
    )

    if status == 'open':
        requests_qs = requests_qs.filter(status__in=ServiceRequest.OPEN_STATUSES)
    elif status in dict(ServiceRequest.Status.choices):
        requests_qs = requests_qs.filter(status=status)

    if kind in dict(ServiceRequest.Kind.choices):
        requests_qs = requests_qs.filter(kind=kind)

    if search:
        requests_qs = requests_qs.filter(
            Q(title__icontains=search)
            | Q(description__icontains=search)
            | Q(reporter_name__icontains=search)
            | Q(reporter_phone__icontains=search)
            | Q(deal__project_code__icontains=search)
            | Q(client__last_name__icontains=search)
            | Q(client__company_name__icontains=search)
        )

    open_count = ServiceRequest.objects.filter(status__in=ServiceRequest.OPEN_STATUSES).count()

    context = {
        'service_requests': requests_qs,
        'open_count': open_count,
        'selected_status': status,
        'selected_kind': kind,
        'search_query': search,
        'status_choices': ServiceRequest.Status.choices,
        'kind_choices': ServiceRequest.Kind.choices,
        'can_edit': _can_edit(request),
    }
    return render(request, 'service_list.html', context)


@login_required
def service_create(request):
    if not _can_edit(request):
        return redirect('service_list')

    if request.method == 'POST':
        form = ServiceRequestForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            if not obj.client_id and obj.deal_id and obj.deal.client_id:
                obj.client = obj.deal.client
            obj.save()
            ServiceRequestEvent.objects.create(
                request=obj,
                author=request.user,
                kind=ServiceRequestEvent.Kind.SYSTEM,
                text=f'Обращение заведено ({obj.get_kind_display()}).',
            )
            record_domain_event(
                actor=request.user,
                event_type='service_request.created',
                entity_model='ServiceRequest',
                entity_id=obj.id,
                payload={
                    'number': obj.number,
                    'kind': obj.kind,
                    'priority': obj.priority,
                    'deal_id': obj.deal_id,
                    'title': obj.title,
                },
                request=request,
            )
            return redirect('service_detail', pk=obj.id)
    else:
        initial = {}
        deal_id = request.GET.get('deal')
        if deal_id:
            initial['deal'] = deal_id
        form = ServiceRequestForm(initial=initial)

    return render(request, 'service_form.html', {'form': form, 'is_edit': False})


@login_required
def service_detail(request, pk):
    service_request = get_object_or_404(
        ServiceRequest.objects.select_related('deal', 'deal__client', 'client', 'assignee', 'created_by'),
        pk=pk,
    )
    events = service_request.events.select_related('author').all()
    context = {
        'sr': service_request,
        'events': events,
        'comment_form': ServiceRequestCommentForm(),
        'status_choices': ServiceRequest.Status.choices,
        'can_edit': _can_edit(request),
    }
    return render(request, 'service_detail.html', context)


@login_required
def service_edit(request, pk):
    service_request = get_object_or_404(ServiceRequest, pk=pk)
    if not _can_edit(request):
        return redirect('service_detail', pk=pk)

    if request.method == 'POST':
        form = ServiceRequestForm(request.POST, instance=service_request)
        if form.is_valid():
            form.save()
            return redirect('service_detail', pk=pk)
    else:
        form = ServiceRequestForm(instance=service_request)
    return render(request, 'service_form.html', {'form': form, 'is_edit': True, 'sr': service_request})


@login_required
@require_POST
def service_update_status(request, pk):
    service_request = get_object_or_404(ServiceRequest, pk=pk)
    if not _can_edit(request):
        return redirect('service_detail', pk=pk)

    new_status = (request.POST.get('status') or '').strip()
    if new_status not in dict(ServiceRequest.Status.choices) or new_status == service_request.status:
        return redirect('service_detail', pk=pk)

    old_status = service_request.status
    service_request.status = new_status
    if new_status in (ServiceRequest.Status.DONE, ServiceRequest.Status.REJECTED):
        service_request.resolved_at = timezone.now()
        resolution = (request.POST.get('resolution') or '').strip()
        if resolution:
            service_request.resolution = resolution
    else:
        service_request.resolved_at = None
    service_request.save()

    ServiceRequestEvent.objects.create(
        request=service_request,
        author=request.user,
        kind=ServiceRequestEvent.Kind.STATUS,
        text=f'{dict(ServiceRequest.Status.choices)[old_status]} → {service_request.get_status_display()}',
    )
    record_domain_event(
        actor=request.user,
        event_type='service_request.status_changed',
        entity_model='ServiceRequest',
        entity_id=service_request.id,
        payload={
            'number': service_request.number,
            'old_status': old_status,
            'new_status': new_status,
            'deal_id': service_request.deal_id,
            'title': service_request.title,
        },
        request=request,
    )
    return redirect('service_detail', pk=pk)


@login_required
@require_POST
def service_add_comment(request, pk):
    service_request = get_object_or_404(ServiceRequest, pk=pk)
    if not _can_edit(request):
        return redirect('service_detail', pk=pk)

    form = ServiceRequestCommentForm(request.POST)
    if form.is_valid():
        ServiceRequestEvent.objects.create(
            request=service_request,
            author=request.user,
            kind=ServiceRequestEvent.Kind.COMMENT,
            text=form.cleaned_data['text'].strip(),
        )
        service_request.save(update_fields=['updated_at'])
    return redirect('service_detail', pk=pk)
