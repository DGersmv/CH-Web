import mimetypes
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Case, IntegerField, Prefetch, Q, Value, When
from django.http import FileResponse, Http404, HttpResponseBadRequest, HttpResponseForbidden
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
from clients.forms import ClientForm
from clients.models import Client
from deals.forms import DashboardLeadForm, DealConfiguratorForm, DealFileUploadForm
from deals.models import ChangeLog, Deal, DealClientMessage, LibraryAsset, ProjectFile, ProjectVersion, ServiceRequest
from deals.services.activity_feed import build_activity_feed
from deals.services.approvals import build_approvals_context
from deals.services.design import build_design_context
from deals.services.storage_paths import ensure_library_dirs, get_files_root
from deals.views import _files_context
from deals.services.bathrooms import bathrooms_button_enabled
from deals.services.calculation_engine import calculate_config
from system_settings.events import record_domain_event
from tasks.models import Task


def _attach_notification_target_urls(notifications):
    task_ids = [
        item.related_id
        for item in notifications
        if item.notification_type == Notification.Type.TASK_ASSIGNED
        and item.related_model == 'Task'
        and item.related_id
    ]
    tasks_by_id = {
        task.id: task
        for task in Task.objects.select_related('deal').filter(pk__in=task_ids)
    }
    for notification in notifications:
        target_url = ''
        if notification.notification_type == Notification.Type.TASK_ASSIGNED and notification.related_id:
            task = tasks_by_id.get(notification.related_id)
            if task and task.deal_id:
                target_url = reverse('deal_detail', args=[task.deal_id])
            else:
                target_url = reverse('tasks')
        notification.target_url = target_url
    return notifications


@login_required
def home(request):
    today = timezone.localdate()
    active_statuses = [
        Deal.Status.NEW,
        Deal.Status.QUALIFIED,
        Deal.Status.SENT_QUOTE,
        Deal.Status.CONTRACT,
        Deal.Status.PREPAYMENT,
        Deal.Status.PRODUCTION,
        Deal.Status.INSTALLATION,
    ]
    active_deals_count = Deal.objects.filter(status__in=active_statuses).count()

    urgent_tasks = (
        Task.objects.select_related('deal')
        .filter(assignee=request.user, is_done=False, due_date__lte=today)
        .order_by('due_date', 'created_at')
    )

    new_leads = (
        Deal.objects.select_related('client')
        .filter(status__in=[Deal.Status.ORPHAN, Deal.Status.NEW])
        .order_by('-created_at')
    )

    priority_rank = Case(
        When(priority=ServiceRequest.Priority.URGENT, then=Value(0)),
        When(priority=ServiceRequest.Priority.HIGH, then=Value(1)),
        When(priority=ServiceRequest.Priority.NORMAL, then=Value(2)),
        default=Value(3),
        output_field=IntegerField(),
    )
    open_service_requests = (
        ServiceRequest.objects.select_related('deal', 'client', 'assignee')
        .filter(status__in=ServiceRequest.OPEN_STATUSES)
        .annotate(priority_rank=priority_rank)
        .order_by('priority_rank', '-created_at')
    )
    open_service_count = open_service_requests.count()

    latest_notifications = _attach_notification_target_urls(
        list(
            Notification.objects.select_related('actor')
            .filter(user=request.user)
            .order_by('-created_at')[:20]
        )
    )

    context = {
        'active_deals_count': active_deals_count,
        'urgent_tasks': urgent_tasks,
        'new_leads': new_leads,
        'open_service_requests': open_service_requests[:8],
        'open_service_count': open_service_count,
        'activity_feed': build_activity_feed(limit=30),
        'lead_form': DashboardLeadForm(),
        'is_leadership': is_leadership(request.user),
        'is_file_only_role': is_file_only_role(request.user),
        'today': today,
        'latest_notifications': latest_notifications,
    }
    return render(request, 'home.html', context)


@login_required
def cabinet(request):
    from deals.services import telegram_link

    profile = telegram_link.get_profile(request.user)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'telegram_code':
            telegram_link.issue_code(request.user)
        elif action == 'telegram_unlink':
            telegram_link.unlink(request.user)
        return redirect('cabinet')

    from django.conf import settings as dj_settings

    code_valid = bool(
        profile.link_code
        and profile.link_code_expires_at
        and profile.link_code_expires_at > timezone.now()
    )
    return render(request, 'cabinet.html', {
        'tg_profile': profile,
        'tg_code_valid': code_valid,
        'tg_bot_configured': bool(getattr(dj_settings, 'TELEGRAM_BOT_TOKEN', '')),
    })


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
        return redirect('home')
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
def files_page(request):
    query_string = request.GET.urlencode()
    target_url = reverse('settings_library')
    if query_string:
        target_url = f'{target_url}?{query_string}'
    return redirect(target_url)


def _normalize_upload_name(filename: str) -> str:
    safe = ''.join(ch for ch in filename if ch not in '/\\').strip()
    return safe or 'file.bin'


def _library_section_dir(section: str) -> str:
    mapping = {
        LibraryAsset.Section.LAYOUT: 'layouts',
        LibraryAsset.Section.CONTRACT_TEMPLATE: 'contracts',
        LibraryAsset.Section.PHOTO: 'photos',
        LibraryAsset.Section.VIDEO: 'videos',
        LibraryAsset.Section.SUPPLIER_FILE: 'suppliers',
    }
    return mapping[section]


def _section_uses_module_groups(section: str) -> bool:
    return section in {
        LibraryAsset.Section.LAYOUT,
        LibraryAsset.Section.PHOTO,
        LibraryAsset.Section.VIDEO,
    }


def _section_uses_supplier_tabs(section: str) -> bool:
    return section == LibraryAsset.Section.SUPPLIER_FILE


def _is_allowed_library_upload(section: str, ext: str) -> bool:
    if section == LibraryAsset.Section.LAYOUT:
        return ext in {'.pdf', '.jpg', '.jpeg', '.png', '.webp'}
    if section == LibraryAsset.Section.CONTRACT_TEMPLATE:
        return ext in {
            '.pdf',
            '.doc',
            '.docx',
            '.xls',
            '.xlsx',
            '.ppt',
            '.pptx',
            '.odt',
            '.ods',
            '.odp',
            '.rtf',
            '.txt',
        }
    if section == LibraryAsset.Section.PHOTO:
        return ext in {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
    if section == LibraryAsset.Section.VIDEO:
        return ext in {'.mp4', '.webm', '.mov', '.avi', '.mkv'}
    if section == LibraryAsset.Section.SUPPLIER_FILE:
        return ext in {
            '.pdf',
            '.jpg',
            '.jpeg',
            '.png',
            '.webp',
            '.gif',
            '.doc',
            '.docx',
            '.xls',
            '.xlsx',
            '.ppt',
            '.pptx',
            '.odt',
            '.ods',
            '.odp',
            '.rtf',
            '.txt',
            '.mp4',
            '.webm',
            '.mov',
            '.avi',
            '.mkv',
        }
    return False


@login_required
@require_POST
def library_asset_upload(request):
    section = (request.POST.get('section') or '').strip()
    module_group = (request.POST.get('module_group') or '').strip()
    supplier_category = (request.POST.get('supplier_category') or '').strip()
    upload = request.FILES.get('upload')
    redirect_base = (request.POST.get('redirect_to') or '').strip() or reverse('settings_library')
    if not redirect_base.startswith('/'):
        redirect_base = reverse('settings_library')
    if not upload:
        return redirect(f"{redirect_base}?section={section}&module_group={module_group}&error=Не выбран файл")
    valid_sections = {value for value, _ in LibraryAsset.Section.choices}
    valid_groups = {value for value, _ in LibraryAsset.ModuleGroup.choices}
    valid_supplier_categories = {value for value, _ in LibraryAsset.SupplierCategory.choices}
    if section not in valid_sections:
        return HttpResponseBadRequest('Invalid upload target')
    if _section_uses_module_groups(section):
        if module_group not in valid_groups:
            return HttpResponseBadRequest('Invalid upload target')
    else:
        module_group = LibraryAsset.ModuleGroup.M1
    if _section_uses_supplier_tabs(section):
        if supplier_category not in valid_supplier_categories:
            return HttpResponseBadRequest('Invalid upload target')
    else:
        supplier_category = ''

    original_name = _normalize_upload_name(upload.name)
    ext = Path(original_name).suffix.lower()
    if not _is_allowed_library_upload(section, ext):
        return redirect(
            f"{redirect_base}?section={section}&module_group={module_group}&error=Недопустимый формат файла"
        )

    ensure_library_dirs()
    stamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    filename = f'{stamp}_{module_group}_{original_name}'
    relative_path = Path('library') / _library_section_dir(section)
    if _section_uses_module_groups(section):
        relative_path = relative_path / module_group
    if _section_uses_supplier_tabs(section):
        relative_path = relative_path / supplier_category
    relative_path = relative_path / filename
    absolute_path = get_files_root() / relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    with absolute_path.open('wb+') as destination:
        for chunk in upload.chunks():
            destination.write(chunk)

    asset = LibraryAsset.objects.create(
        section=section,
        module_group=module_group,
        supplier_category=supplier_category,
        relative_path=str(relative_path).replace('\\', '/'),
        original_name=original_name,
        size_bytes=upload.size,
        mime_type=(getattr(upload, 'content_type', '') or mimetypes.guess_type(original_name)[0] or ''),
        ext=ext.lstrip('.'),
        uploaded_by=request.user,
    )
    record_domain_event(
        actor=request.user,
        event_type='project_file.uploaded',
        entity_model='LibraryAsset',
        entity_id=asset.id,
        payload={
            'section': section,
            'module_group': module_group,
            'supplier_category': supplier_category,
            'original_name': original_name,
        },
        request=request,
    )
    redirect_url = f"{redirect_base}?section={section}&module_group={module_group}"
    if supplier_category:
        redirect_url += f"&supplier_category={supplier_category}"
    return redirect(redirect_url)


@login_required
def library_asset_download(request, asset_id):
    asset = get_object_or_404(LibraryAsset, pk=asset_id)
    absolute_path = asset.absolute_path
    if not absolute_path.exists() or not absolute_path.is_file():
        raise Http404('File not found')
    return FileResponse(absolute_path.open('rb'), as_attachment=True, filename=asset.original_name)


@login_required
def client_create(request):
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save(commit=False)
            client.created_by = request.user
            client.save()
            return redirect('clients')
    else:
        form = ClientForm()
    return render(request, 'client_form.html', {'form': form, 'is_edit': False})


@login_required
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            return redirect('clients')
    else:
        form = ClientForm(instance=client)
    return render(request, 'client_form.html', {'form': form, 'client': client, 'is_edit': True})


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
        .filter(
            Q(last_name__icontains=query)
            | Q(first_name__icontains=query)
            | Q(middle_name__icontains=query)
            | Q(company_name__icontains=query)
        )
        .order_by('company_name', 'last_name', 'first_name')[:5]
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
            url = reverse('client_edit', kwargs={'pk': client.pk})
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
                | Q(client__last_name__icontains=search)
                | Q(client__first_name__icontains=search)
                | Q(client__middle_name__icontains=search)
                | Q(client__company_name__icontains=search)
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
    def _parse_money(value):
        if value is None:
            return None
        try:
            return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError, TypeError):
            return None

    @classmethod
    def _extract_total(cls, version):
        if not version or not version.frozen_data:
            return None
        data = version.frozen_data
        if isinstance(data, dict):
            calc = data.get('calculation')
            if isinstance(calc, dict):
                totals = calc.get('totals') or {}
                with_margin = cls._parse_money(totals.get('with_margin'))
                if with_margin is not None:
                    add_opts = calc.get('additional_options') or {}
                    add_sub = cls._parse_money(add_opts.get('subtotal'))
                    if add_sub is None:
                        add_sub = Decimal('0.00')
                    return (with_margin + add_sub).quantize(
                        Decimal('0.01'),
                        rounding=ROUND_HALF_UP,
                    )
        candidates = (
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

        versions_list = list(
            ProjectVersion.objects.filter(deal=self.object)
            .select_related('created_by')
            .order_by('-version_number')
        )
        context['versions'] = versions_list
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
        recent_messages_qs = (
            DealClientMessage.objects.filter(deal=self.object)
            .select_related('author_user')
            .prefetch_related('attachments', 'attachments__project_file')
            .order_by('-created_at')
        )
        context['client_messages_latest'] = recent_messages_qs.first()
        context['client_messages_recent'] = list(reversed(list(recent_messages_qs[:20])))
        context['client_portal_url'] = self.request.build_absolute_uri(
            reverse('client_portal_entry', kwargs={'deal_id': self.object.id})
        )
        context.update(build_approvals_context(self.object))
        context.update(build_design_context(self.object))
        context['deal_project_files_for_attach'] = (
            ProjectFile.objects.filter(deal=self.object, is_archived=False).order_by('-updated_at')[:200]
        )
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

