from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from accounts.forms import EmployeeCreateForm, EmployeeUpdateForm
from accounts.forms import DashboardMessageForm
from accounts.events import create_notification, log_audit_event, push_user_event
from accounts.models import DirectMessage, Notification
from accounts.permissions import is_file_only_role, is_leadership
from clients.models import Client
from deals.forms import DashboardLeadForm, DealConfiguratorForm, DealFileUploadForm
from deals.models import ChangeLog, Deal, ProjectFile, ProjectVersion
from deals.views import _files_context
from deals.services.bathrooms import bathrooms_button_enabled
from deals.services.calculation_engine import calculate_config
from tasks.models import Task


def _display_name(user):
    full_name = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip()
    return full_name or user.username


@login_required
def home(request):
    today = timezone.localdate()
    active_statuses = [Deal.Status.NEW, Deal.Status.QUALIFIED, Deal.Status.SENT_QUOTE, Deal.Status.CONTRACT, Deal.Status.PREPAYMENT, Deal.Status.PRODUCTION, Deal.Status.INSTALLATION]
    my_active_deals = (
        Deal.objects.select_related('client')
        .filter(assigned_manager=request.user, status__in=active_statuses)
        .order_by('-updated_at')
    )
    urgent_tasks = (
        Task.objects.select_related('deal')
        .filter(assignee=request.user, is_done=False, due_date__lte=today)
        .order_by('due_date', 'created_at')
    )
    archicad_updates = (
        ProjectVersion.objects.select_related('deal', 'created_by')
        .filter(source=ProjectVersion.Source.ARCHICAD)
        .order_by('-created_at')[:10]
    )
    stale_deals = (
        Deal.objects.select_related('client', 'assigned_manager')
        .exclude(status__in=[Deal.Status.DELIVERED, Deal.Status.LOST])
        .filter(updated_at__lt=timezone.now() - timedelta(days=7))
        .order_by('updated_at')
    )
    for deal in stale_deals:
        deal.silent_days = max((today - deal.updated_at.date()).days, 0)
    new_leads = (
        Deal.objects.select_related('client')
        .filter(assigned_manager__isnull=True, status__in=[Deal.Status.ORPHAN, Deal.Status.NEW])
        .order_by('-created_at')
    )

    dialog_with_raw = request.GET.get('dialog_with', '').strip()
    dialog_user = None
    if dialog_with_raw.isdigit():
        dialog_user = request.user.__class__.objects.filter(pk=int(dialog_with_raw), is_active=True).exclude(pk=request.user.pk).first()

    all_dialog_messages = list(
        DirectMessage.objects.select_related('sender', 'recipient')
        .filter(Q(sender=request.user) | Q(recipient=request.user))
        .order_by('-created_at')[:500]
    )
    dialog_map = {}
    for msg in all_dialog_messages:
        counterpart = msg.recipient if msg.sender_id == request.user.id else msg.sender
        item = dialog_map.get(counterpart.id)
        if item is None:
            dialog_map[counterpart.id] = {
                'user': counterpart,
                'display_name': _display_name(counterpart),
                'last_message': msg.body or (f'Файл: {msg.attachment.name.split("/")[-1]}' if msg.attachment else ''),
                'last_created_at': msg.created_at,
                'unread_count': 0,
            }
        if msg.recipient_id == request.user.id and msg.read_at is None:
            dialog_map[counterpart.id]['unread_count'] += 1
    dialogs = sorted(dialog_map.values(), key=lambda x: x['last_created_at'], reverse=True)
    existing_dialog_user_ids = {item['user'].id for item in dialogs}
    for user_item in request.user.__class__.objects.filter(is_active=True).exclude(pk=request.user.pk):
        if user_item.id in existing_dialog_user_ids:
            continue
        dialogs.append(
            {
                'user': user_item,
                'display_name': _display_name(user_item),
                'last_message': '',
                'last_created_at': datetime(1970, 1, 1, tzinfo=timezone.get_current_timezone()),
                'unread_count': 0,
            }
        )
    dialogs = sorted(dialogs, key=lambda x: x['last_created_at'], reverse=True)

    if dialog_user is None and dialogs:
        dialog_user = dialogs[0]['user']

    dialog_messages = []
    if dialog_user is not None:
        DirectMessage.objects.filter(
            sender=dialog_user,
            recipient=request.user,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
        dialog_messages = (
            DirectMessage.objects.select_related('sender', 'recipient')
            .filter(
                Q(sender=request.user, recipient=dialog_user)
                | Q(sender=dialog_user, recipient=request.user)
            )
            .order_by('created_at')[:200]
        )

    context = {
        'my_active_deals': my_active_deals,
        'urgent_tasks': urgent_tasks,
        'archicad_updates': archicad_updates,
        'stale_deals': stale_deals,
        'new_leads': new_leads,
        'lead_form': DashboardLeadForm(),
        'is_leadership': is_leadership(request.user),
        'today': today,
        'message_form': DashboardMessageForm(current_user=request.user, initial={'recipient': dialog_user.id if dialog_user else None}),
        'dialogs': dialogs,
        'dialog_user': dialog_user,
        'dialog_messages': dialog_messages,
        'latest_notifications': Notification.objects.select_related('actor').filter(user=request.user)[:10],
    }

    if is_leadership(request.user):
        context['pipeline_total'] = Deal.objects.exclude(status__in=[Deal.Status.DELIVERED, Deal.Status.LOST]).count()
        context['stale_deals_count'] = Deal.objects.filter(updated_at__lt=timezone.now() - timedelta(days=7)).count()
        user_model = get_user_model()
        context['employees'] = user_model.objects.order_by('username')
        context['employee_create_form'] = EmployeeCreateForm()

    return render(request, 'home.html', context)


@login_required
@require_POST
def dashboard_message_send(request):
    form = DashboardMessageForm(request.POST, request.FILES, current_user=request.user)
    if form.is_valid():
        message = DirectMessage.objects.create(
            sender=request.user,
            recipient=form.cleaned_data['recipient'],
            body=form.cleaned_data['body'].strip(),
            attachment=form.cleaned_data.get('attachment'),
        )
        create_notification(
            user=message.recipient,
            actor=request.user,
            notification_type='message_received',
            title='Новое сообщение',
            body=(message.body or '').strip() or (f'Файл: {message.attachment.name.split("/")[-1]}' if message.attachment else ''),
            related_model='DirectMessage',
            related_id=message.id,
        )
        push_user_event(
            user_id=message.recipient_id,
            payload={
                'type': 'message.created',
                'message': {
                    'id': message.id,
                    'sender_id': message.sender_id,
                    'recipient_id': message.recipient_id,
                    'body': message.body,
                    'created_at': message.created_at.isoformat(),
                },
            },
        )
        log_audit_event(
            actor=request.user,
            event_type='message.sent',
            entity_model='DirectMessage',
            entity_id=message.id,
            payload={
                'recipient_id': message.recipient_id,
                'has_attachment': bool(message.attachment),
            },
            request=request,
        )
        return redirect(f"{reverse('home')}?dialog_with={form.cleaned_data['recipient'].id}")
    return redirect('home')


@login_required
@require_POST
def notifications_mark_all_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True, read_at=timezone.now())
    return redirect('home')


@login_required
@require_POST
def dashboard_employee_create(request):
    if not is_leadership(request.user):
        return HttpResponseForbidden('Not allowed')
    user_model = get_user_model()
    form = EmployeeCreateForm(request.POST)
    if form.is_valid():
        form.save()
        form = EmployeeCreateForm()
    employees = user_model.objects.order_by('username')
    return render(
        request,
        'includes/dashboard_employees_block.html',
        {'employees': employees, 'employee_create_form': form},
        status=200 if not form.errors else 400,
    )


@login_required
@require_POST
def dashboard_employee_update(request, user_id):
    if not is_leadership(request.user):
        return HttpResponseForbidden('Not allowed')
    user_model = get_user_model()
    employee = get_object_or_404(user_model, pk=user_id)
    form = EmployeeUpdateForm(request.POST, instance=employee)
    if form.is_valid():
        proposed_role = form.cleaned_data['role']
        proposed_active = form.cleaned_data['is_active']
        if employee.id == request.user.id and (proposed_role not in {'head', 'admin'} or not proposed_active):
            return HttpResponseForbidden('Cannot remove your own leadership access')
        current_role = employee.role
        current_active = employee.is_active
        leadership_count = user_model.objects.filter(role__in=['head', 'admin'], is_active=True).count()
        if current_role in {'head', 'admin'} and current_active and (proposed_role not in {'head', 'admin'} or not proposed_active):
            if leadership_count <= 1:
                return HttpResponseForbidden('Cannot remove last leadership user')
        form.save()
    employees = user_model.objects.order_by('username')
    return render(
        request,
        'includes/dashboard_employees_block.html',
        {'employees': employees, 'employee_create_form': EmployeeCreateForm()},
        status=200 if not form.errors else 400,
    )


@login_required
def deals_page(request):
    return render(request, 'deal_list.html')


@login_required
def tasks_page(request):
    return render(request, 'task_list.html')


@login_required
def clients_page(request):
    clients = (
        Client.objects.prefetch_related('deals')
        .order_by('-created_at')
    )
    return render(request, 'client_list.html', {'clients': clients})


@login_required
def logout_and_redirect(request):
    auth_logout(request)
    return redirect('login')


@login_required
def global_search(request):
    query = request.GET.get('q', '').strip()
    if not query:
        return render(request, 'includes/global_search_results.html', {'query': '', 'results': []})

    deal_results = (
        Deal.objects.select_related('client')
        .filter(project_code__icontains=query)
        .order_by('-updated_at')[:5]
    )
    client_matches = (
        Client.objects.prefetch_related('deals')
        .filter(full_name__icontains=query)
        .order_by('full_name')[:5]
    )

    results = []
    for deal in deal_results:
        results.append(
            {
                'type': 'deal',
                'label': f'{deal.project_code}',
                'subtitle': f'Клиент: {deal.client.full_name}' if deal.client else 'Клиент не указан',
                'url': reverse('deal_detail', kwargs={'pk': deal.pk}),
            }
        )

    for client in client_matches:
        target_deal = client.deals.order_by('-updated_at').first()
        if target_deal:
            url = reverse('deal_detail', kwargs={'pk': target_deal.pk})
            subtitle = f'Клиент -> сделка {target_deal.project_code}'
        else:
            url = reverse('clients')
            subtitle = 'Клиент (без сделок)'
        results.append(
            {
                'type': 'client',
                'label': client.full_name,
                'subtitle': subtitle,
                'url': url,
            }
        )

    return render(request, 'includes/global_search_results.html', {'query': query, 'results': results[:10]})


class DealListView(LoginRequiredMixin, ListView):
    model = Deal
    template_name = 'deal_list.html'
    context_object_name = 'deals'
    paginate_by = 25

    def get_queryset(self):
        queryset = (
            Deal.objects.select_related('client', 'assigned_manager')
            .prefetch_related(
                Prefetch(
                    'versions',
                    queryset=ProjectVersion.objects.order_by('-version_number'),
                    to_attr='versions_for_list',
                )
            )
            .order_by('-updated_at')
        )
        status = self.request.GET.get('status', '').strip()
        module_count = self.request.GET.get('module_count', '').strip()
        manager_id = self.request.GET.get('assigned_manager', '').strip()
        mine = self.request.GET.get('mine', '').strip()
        search = self.request.GET.get('q', '').strip()

        if status and status in dict(Deal.Status.choices):
            queryset = queryset.filter(status=status)

        if module_count.isdigit():
            queryset = queryset.filter(module_count=int(module_count))

        if manager_id.isdigit():
            queryset = queryset.filter(assigned_manager_id=int(manager_id))

        if mine == '1':
            queryset = queryset.filter(assigned_manager=self.request.user)

        if search:
            queryset = queryset.filter(
                Q(project_code__icontains=search)
                | Q(client__full_name__icontains=search)
                | Q(client__phone__icontains=search)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_status = self.request.GET.get('status', '').strip()
        selected_module_count = self.request.GET.get('module_count', '').strip()
        selected_manager = self.request.GET.get('assigned_manager', '').strip()
        selected_mine = self.request.GET.get('mine', '').strip()
        search_query = self.request.GET.get('q', '').strip()

        for deal in context['deals']:
            latest_version = deal.versions_for_list[0] if deal.versions_for_list else None
            deal.latest_total = self._extract_total(latest_version)

        context['status_choices'] = Deal.Status.choices
        context['module_choices'] = [3, 5, 7, 9, 11]
        context['manager_choices'] = (
            self.request.user.__class__.objects.filter(role='manager').order_by('username')
        )
        context['selected_status'] = selected_status
        context['selected_module_count'] = selected_module_count
        context['selected_manager'] = selected_manager
        context['selected_mine'] = selected_mine == '1'
        context['search_query'] = search_query
        context['current_filters'] = self._build_filter_query_without_page()
        context['can_view_latest_total'] = is_leadership(self.request.user)
        return context

    def _build_filter_query_without_page(self):
        params = self.request.GET.copy()
        params.pop('page', None)
        return params.urlencode()

    @staticmethod
    def _extract_total(version):
        if not version or not version.frozen_data:
            return None
        data = version.frozen_data
        candidates = (
            ('calculation', 'totals', 'with_margin'),
            ('calculation', 'totals', 'subtotal'),
            ('calculation', 'totals', 'total'),
            ('cost_summary', 'with_margin'),
            ('total_amount',),
            ('total',),
            ('summary', 'total'),
            ('totals', 'grand_total'),
            ('totals', 'total'),
            ('price', 'total'),
        )
        for path in candidates:
            value = data
            for key in path:
                if not isinstance(value, dict) or key not in value:
                    value = None
                    break
                value = value[key]
            if value is None:
                continue
            try:
                return Decimal(str(value))
            except (InvalidOperation, ValueError, TypeError):
                continue
        return None


class DealDetailView(LoginRequiredMixin, DetailView):
    model = Deal
    template_name = 'deal_detail.html'
    context_object_name = 'deal'

    def get_queryset(self):
        return (
            Deal.objects.select_related('client', 'assigned_manager')
            .prefetch_related(
                Prefetch('versions', queryset=ProjectVersion.objects.select_related('created_by').order_by('-version_number')),
                Prefetch('tasks', queryset=self._task_queryset()),
            )
        )

    def _task_queryset(self):
        from tasks.models import Task

        return Task.objects.select_related('assignee').order_by('is_done', 'due_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        draft_version = self.object.versions.filter(status=ProjectVersion.Status.DRAFT).order_by('-version_number').first()
        if draft_version is None:
            draft_version = self.object.create_new_version(source='manual', created_by=self.request.user)
        frozen = draft_version.frozen_data or {}
        config_inputs = frozen.get('config_inputs')
        config_form = DealConfiguratorForm(initial=config_inputs) if config_inputs else DealConfiguratorForm(
            initial={
                'building_area': '120',
                'living_area': '90',
                'ceiling_height': '2.7',
                'floor_150_qty': '0',
                'floor_200_qty': '120',
                'floor_250_qty': '0',
                'floor_laminate_qty': '90',
                'floor_tile_qty': '0',
                'facade_planken_lm': '0',
                'facade_combined_lm': '48',
                'partition_double_lm': '24',
                'partition_single_lm': '16',
                'finish_quarter_lm': '0',
                'finish_ldsp_lm': '48',
                'finish_gkl_lm': '0',
                'finish_mdf_lm': '0',
                'finish_plywood_lm': '0',
                'bathroom_tile_lm': '0',
                'roof_gable_qty': '120',
                'roof_flat_qty': '0',
                'interior_doors_count': 5,
                'windows_count': 8,
                'windows_total_cost': '0',
                'panoramic_sections_count': 0,
                'panoramic_sections_total_cost': '0',
                'sauna_cost': '0',
                'sauna_installation_cost': '0',
                'bathrooms_count': 1,
            }
        )
        calc_result = frozen.get('calculation')
        if calc_result is None:
            calc_result = calculate_config(
                config_form.initial,
                margin_percent=self.object.margin_percent,
                version=draft_version,
            )

        context['versions'] = self.object.versions.all()
        context['tasks_for_deal'] = self.object.tasks.all()
        context['status_choices'] = Deal.Status.choices
        context['manager_choices'] = self.request.user.__class__.objects.filter(role='manager').order_by('username')
        context['is_file_only_role'] = is_file_only_role(self.request.user)
        context['is_leadership'] = is_leadership(self.request.user)
        context['draft_version'] = draft_version
        context['config_form'] = config_form
        context['calc_result'] = calc_result
        context['save_success'] = False
        context['bathrooms_button_enabled'] = bathrooms_button_enabled(frozen)
        context['change_logs'] = ChangeLog.objects.filter(project_version__deal=self.object).select_related(
            'project_version', 'changed_by'
        )[:20]
        context.update(_files_context(self.object, viewer=self.request.user))
        totals = (calc_result or {}).get('totals', {}) if isinstance(calc_result, dict) else {}
        additional_options = (calc_result or {}).get('additional_options', {}) if isinstance(calc_result, dict) else {}
        materials = self._as_money_decimal(totals.get('material_total'))
        work = self._as_money_decimal(totals.get('work_total'))
        subtotal = self._as_money_decimal(totals.get('subtotal'))
        with_margin = self._as_money_decimal(totals.get('with_margin'))
        additional_options_total = self._as_money_decimal(additional_options.get('subtotal')) or Decimal('0.00')
        total_for_customer = ((with_margin or Decimal('0.00')) + additional_options_total).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP,
        )
        building_area_value = self._as_decimal(config_form.initial.get('building_area'))
        cost_per_m2 = None
        if building_area_value and building_area_value > 0 and with_margin is not None:
            cost_per_m2 = (with_margin / building_area_value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        saved_at_raw = (frozen.get('saved_at') if isinstance(frozen, dict) else None) or draft_version.created_at
        saved_at = saved_at_raw
        if isinstance(saved_at_raw, str):
            try:
                saved_at = datetime.fromisoformat(saved_at_raw)
            except ValueError:
                saved_at = draft_version.created_at
        context['cost_summary'] = {
            'materials_total': materials or Decimal('0.00'),
            'work_total': work or Decimal('0.00'),
            'subtotal': subtotal or Decimal('0.00'),
            'with_margin': with_margin or Decimal('0.00'),
            'additional_options_total': additional_options_total,
            'total_for_customer': total_for_customer,
            'margin_percent': self._as_decimal(totals.get('margin_percent')) or Decimal(str(self.object.margin_percent)),
            'saved_at': saved_at,
            'building_area': building_area_value or Decimal('0.00'),
            'cost_per_m2': cost_per_m2,
        }
        return context

    @staticmethod
    def _as_decimal(value):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    def _as_money_decimal(self, value):
        parsed = self._as_decimal(value)
        if parsed is None:
            return None
        return parsed.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
