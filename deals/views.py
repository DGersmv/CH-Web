import io
import json
import mimetypes
import shutil
import zipfile

from django.utils.text import slugify
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic.edit import FormView
from django.utils import timezone

from accounts.permissions import can_access_file_source, can_use_umnik_chat, is_file_only_role, umnik_capabilities
from clients.models import Client, parse_quick_client_name

from .forms import (
    AdditionalOptionCreateForm,
    AdditionalOptionLineFormSet,
    BathroomLineFormSet,
    DashboardLeadForm,
    DealConfiguratorForm,
    DealCreateForm,
    DealFileUploadForm,
)
from .client_portal import create_portal_session, get_portal_session, touch_session
from .models import (
    ChangeLog,
    Deal,
    DealApproval,
    DealDesignSection,
    DealBathroom,
    DealClientMessage,
    DealClientMessageAttachment,
    ProjectFile,
    ProjectVersion,
    UmnikChatAttachment,
    UmnikChatThread,
    build_project_code_from_parts,
    normalize_project_code,
)
from .services.bathrooms import (
    bathroom_totals,
    bathrooms_button_enabled,
    bathrooms_count_from_config,
    bathrooms_totals,
    ensure_bathrooms,
    get_template_section,
)
from .services.additional_options import additional_options_rows, additional_options_totals, ensure_additional_option_lines
from .services.approvals import approvals_gate, build_approvals_context, ensure_deal_approvals
from .services.design import build_design_context, design_gate, ensure_deal_design_sections
from .services.storage_paths import ensure_deal_dirs, get_deal_root, get_files_root
from .services.calculation_engine import CALC_SCHEMA_VERSION, calculate_config
from .services import umnik_chat as umnik_chat_store
from .services.umnik import ask_umnik_chat, fetch_archive, lookup_deal_archive

from catalog.forms import COST_ITEM_UNIT_CHOICES_RU
from system_settings.events import record_domain_event
from system_settings.services import get_default_margin_percent


@login_required
@require_POST
def update_deal_status(request, deal_id):
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    new_status = request.POST.get('status', '').strip()
    valid_statuses = {value for value, _ in Deal.Status.choices}
    if new_status not in valid_statuses:
        return HttpResponseBadRequest('Invalid status')

    old_status = deal.status
    if old_status != new_status:
        deal.status = new_status
        deal.save(update_fields=['status', 'updated_at'])

        last_version = deal.versions.order_by('-version_number').first()
        if last_version is None:
            last_version = deal.create_new_version(source='manual', created_by=request.user)

        ChangeLog.objects.create(
            project_version=last_version,
            changed_by=request.user,
            field_path='status',
            old_value={'value': old_status},
            new_value={'value': new_status},
        )
        record_domain_event(
            actor=request.user,
            event_type='deal.status_changed',
            entity_model='Deal',
            entity_id=deal.id,
            payload={
                'old_status': old_status,
                'new_status': new_status,
            },
            request=request,
        )

    return render(
        request,
        'includes/deal_status_block.html',
        {'deal': deal, 'status_choices': Deal.Status.choices},
    )


def _ensure_latest_version_for_log(deal, user):
    last_version = deal.versions.order_by('-version_number').first()
    if last_version is None:
        last_version = deal.create_new_version(source='manual', created_by=user)
    return last_version


@login_required
@require_POST
def update_deal_manager(request, deal_id):
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    manager_id = request.POST.get('assigned_manager', '').strip()
    manager = None
    if manager_id:
        if not manager_id.isdigit():
            return HttpResponseBadRequest('Invalid manager id')
        manager = request.user.__class__.objects.filter(id=int(manager_id), role='manager').first()
        if manager is None:
            return HttpResponseBadRequest('Invalid manager')

    old_manager = deal.assigned_manager.username if deal.assigned_manager else None
    new_manager = manager.username if manager else None
    if deal.assigned_manager_id != (manager.id if manager else None):
        deal.assigned_manager = manager
        deal.save(update_fields=['assigned_manager', 'updated_at'])
        ChangeLog.objects.create(
            project_version=_ensure_latest_version_for_log(deal, request.user),
            changed_by=request.user,
            field_path='assigned_manager',
            old_value={'value': old_manager},
            new_value={'value': new_manager},
        )

    manager_choices = request.user.__class__.objects.filter(role='manager').order_by('username')
    return render(
        request,
        'includes/deal_manager_block.html',
        {'deal': deal, 'manager_choices': manager_choices},
    )


@login_required
@require_POST
def update_deal_margin(request, deal_id):
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    raw_margin = request.POST.get('margin_percent', '').strip().replace(',', '.')
    try:
        new_margin = float(raw_margin)
    except ValueError:
        return HttpResponseBadRequest('Invalid margin')

    old_margin = float(deal.margin_percent)
    if old_margin != new_margin:
        deal.margin_percent = new_margin
        deal.save(update_fields=['margin_percent', 'updated_at'])
        ChangeLog.objects.create(
            project_version=_ensure_latest_version_for_log(deal, request.user),
            changed_by=request.user,
            field_path='margin_percent',
            old_value={'value': old_margin},
            new_value={'value': new_margin},
        )

    return render(request, 'includes/deal_margin_block.html', {'deal': deal})


# Модуль автоматических расчётов (сметы, санузлы, доп.опции, электрика) временно
# отключён: цену менеджер проставляет вручную в поле «Договорная цена».
# Код расчётов не удалён — при необходимости вернуть, поставить True.
CONFIGURATOR_ENABLED = getattr(settings, 'CONFIGURATOR_ENABLED', False)


def _configurator_disabled_response(request, deal_id):
    """Единый ответ для отключённых страниц расчётов."""
    messages.info(
        request,
        'Модуль автоматических расчётов отключён. Договорную цену внесите вручную в карточке сделки.',
    )
    target_url = reverse('deal_detail', kwargs={'pk': deal_id})
    if request.headers.get('HX-Request') == 'true':
        response = HttpResponse('')
        response['HX-Redirect'] = target_url
        return response
    return redirect(target_url)


@login_required
@require_POST
def update_deal_agreed_price(request, deal_id):
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)

    raw_price = (request.POST.get('agreed_price') or '').strip().replace(' ', '').replace(',', '.')
    note = (request.POST.get('agreed_price_note') or '').strip()[:300]

    new_price = None
    if raw_price:
        try:
            new_price = Decimal(raw_price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            return HttpResponseBadRequest('Invalid price')
        if new_price < 0:
            return HttpResponseBadRequest('Invalid price')

    old_price = deal.agreed_price
    if old_price != new_price or deal.agreed_price_note != note:
        deal.agreed_price = new_price
        deal.agreed_price_note = note
        deal.agreed_price_updated_at = timezone.now()
        deal.save(update_fields=[
            'agreed_price', 'agreed_price_note', 'agreed_price_updated_at', 'updated_at',
        ])
        ChangeLog.objects.create(
            project_version=_ensure_latest_version_for_log(deal, request.user),
            changed_by=request.user,
            field_path='agreed_price',
            old_value={'value': str(old_price) if old_price is not None else None},
            new_value={'value': str(new_price) if new_price is not None else None, 'note': note},
        )

    return render(
        request,
        'includes/deal_price_block.html',
        {'deal': deal, 'is_file_only_role': is_file_only_role(request.user)},
    )


@login_required
@require_GET
def deal_archive(request, deal_id):
    deal = get_object_or_404(Deal, pk=deal_id)
    archive = lookup_deal_archive(deal)
    return render(
        request,
        'includes/deal_archive_block.html',
        {
            'deal': deal,
            'archive': archive,
        },
    )


@login_required
@require_GET
def archive_search(request):
    query = (request.GET.get('q') or '').strip()
    archive = fetch_archive(query, limit=20) if query else {'ok': True, 'query': '', 'layouts': [], 'error': ''}
    return render(request, 'archive_search.html', {'query': query, 'archive': archive})


def _umnik_denied():
    return JsonResponse({'ok': False, 'error': 'forbidden', 'answer': 'Сначала войдите в CRM.'}, status=403)


def _umnik_json_body(request) -> dict:
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


@login_required
@require_GET
def umnik_chat_bootstrap(request):
    if not can_use_umnik_chat(request.user):
        return _umnik_denied()
    threads = [umnik_chat_store.serialize_thread(item) for item in umnik_chat_store.user_threads(request.user)]
    deals = list(umnik_chat_store.visible_deals())
    return JsonResponse({'ok': True, 'threads': threads, 'deals': deals})


@login_required
@require_POST
def umnik_chat_new(request):
    if not can_use_umnik_chat(request.user):
        return _umnik_denied()
    payload = _umnik_json_body(request)
    kind = str(payload.get('kind') or UmnikChatThread.Kind.GENERAL).strip()
    deal = None
    if kind == UmnikChatThread.Kind.DEAL:
        try:
            deal_id = int(payload.get('deal_id'))
        except (TypeError, ValueError):
            return JsonResponse({'ok': False, 'error': 'deal_required'}, status=400)
        deal = Deal.objects.filter(pk=deal_id).first()
        if deal is None:
            return JsonResponse({'ok': False, 'error': 'deal not found'}, status=404)
    try:
        thread = umnik_chat_store.create_thread(request.user, kind=kind, deal=deal)
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'deal_required'}, status=400)
    return JsonResponse({'ok': True, 'thread': umnik_chat_store.serialize_thread(thread), 'messages': []})


@login_required
@require_GET
def umnik_chat_thread(request, thread_id):
    if not can_use_umnik_chat(request.user):
        return _umnik_denied()
    thread = umnik_chat_store.get_thread(request.user, thread_id)
    if thread is None:
        return JsonResponse({'ok': False, 'error': 'not_found'}, status=404)
    messages = [
        umnik_chat_store.serialize_message(item)
        for item in thread.messages.prefetch_related('attachments').all()
    ]
    return JsonResponse({'ok': True, 'thread': umnik_chat_store.serialize_thread(thread), 'messages': messages})


def _umnik_thread_for_request(request, payload):
    """Существующая нить или новая (general/deal) по данным запроса."""
    thread = umnik_chat_store.get_thread(request.user, payload.get('thread_id'))
    if thread is not None:
        return thread, None
    if payload.get('deal_id') not in (None, ''):
        deal = Deal.objects.filter(pk=payload.get('deal_id')).first()
        if deal is None:
            return None, JsonResponse({'ok': False, 'error': 'deal not found', 'answer': 'Проект не найден.'}, status=404)
        return umnik_chat_store.ensure_deal_thread(request.user, deal), None
    return umnik_chat_store.create_thread(request.user, kind=UmnikChatThread.Kind.GENERAL), None


@login_required
@require_POST
def umnik_chat_upload(request):
    """Загрузка файла/фото в общий чат (multipart) или подтягивание файла с сервера (JSON)."""
    if not can_use_umnik_chat(request.user):
        return _umnik_denied()

    if request.content_type and request.content_type.startswith('multipart/'):
        thread = umnik_chat_store.get_thread(request.user, request.POST.get('thread_id'))
        if thread is None:
            deal = None
            if request.POST.get('deal_id') not in (None, ''):
                deal = Deal.objects.filter(pk=request.POST.get('deal_id')).first()
            thread = (
                umnik_chat_store.ensure_deal_thread(request.user, deal)
                if deal is not None
                else umnik_chat_store.create_thread(request.user, kind=UmnikChatThread.Kind.GENERAL)
            )
        uploaded = request.FILES.get('file')
        if uploaded is None:
            return JsonResponse({'ok': False, 'error': 'no_file', 'answer': 'Файл не выбран.'}, status=400)
        limit = int(getattr(settings, 'UMNIK_CHAT_MAX_UPLOAD_MB', 40)) * 1024 * 1024
        if uploaded.size > limit:
            return JsonResponse({'ok': False, 'error': 'too_big', 'answer': f'Файл больше {limit // (1024 * 1024)} МБ.'}, status=400)
        att = umnik_chat_store.save_upload(thread, uploaded, request.user)
        return JsonResponse({'ok': True, 'thread_id': thread.id, 'attachment': umnik_chat_store.serialize_attachment(att)})

    payload = _umnik_json_body(request)
    raw_path = str(payload.get('server_path') or '').strip()
    if not raw_path:
        return JsonResponse({'ok': False, 'error': 'no_path', 'answer': 'Укажите путь к файлу на сервере.'}, status=400)
    src = umnik_chat_store.resolve_server_path(raw_path)
    if src is None:
        return JsonResponse(
            {'ok': False, 'error': 'not_allowed',
             'answer': 'Файл не найден или путь вне разрешённых папок (Общая_Рабочая, umnik, crm_files).'},
            status=400,
        )
    thread, err = _umnik_thread_for_request(request, payload)
    if err is not None:
        return err
    att = umnik_chat_store.save_server_file(thread, src, raw_path, request.user)
    return JsonResponse({'ok': True, 'thread_id': thread.id, 'attachment': umnik_chat_store.serialize_attachment(att)})


@login_required
@xframe_options_sameorigin
@require_GET
def umnik_chat_open_attachment(request, attachment_id):
    if not can_use_umnik_chat(request.user):
        return HttpResponseForbidden('Not allowed')
    att = get_object_or_404(
        UmnikChatAttachment.objects.select_related('thread'),
        pk=attachment_id,
    )
    if att.thread.user_id != request.user.id and not request.user.is_superuser:
        return HttpResponseForbidden('Not allowed')
    path = att.absolute_path
    if not path.exists() or not path.is_file():
        raise Http404('File not found')
    return FileResponse(path.open('rb'), as_attachment=False, filename=att.original_name)


@login_required
@require_POST
def umnik_chat_send(request):
    if not can_use_umnik_chat(request.user):
        return _umnik_denied()
    payload = _umnik_json_body(request)
    message = str(payload.get('message') or '').strip()
    attach_ids = payload.get('attachment_ids') or []
    thread, err = _umnik_thread_for_request(request, payload)
    if err is not None:
        return err
    atts = umnik_chat_store.pending_attachments(thread, attach_ids)
    if not message and not atts:
        return JsonResponse({'ok': False, 'error': 'empty', 'answer': 'Напишите вопрос или прикрепите файл.'}, status=400)

    compact = umnik_chat_store.thread_history(thread)
    user_msg = umnik_chat_store.append_message(thread, 'user', message, has_attachments=bool(atts))
    umnik_chat_store.link_attachments(user_msg, atts)

    result = ask_umnik_chat(
        message=message or '(файл без комментария)',
        history=compact,
        actor=request.user.username,
        deal_id=thread.deal_id,
        deal_code=thread.deal.project_code if thread.deal_id else '',
        capabilities=umnik_capabilities(request.user),
        attachments=umnik_chat_store.model_attachments(atts),
    )
    answer = (result.get('answer') or '').strip() or 'Пустой ответ.'
    answer_attachments = []
    if result.get('ok'):
        answer_msg = umnik_chat_store.append_message(thread, 'assistant', answer)
        added = []
        for item in result.get('attachments') or []:
            raw = item.get('path') or item.get('server_path') if isinstance(item, dict) else str(item)
            src = umnik_chat_store.resolve_server_path(raw or '')
            if src is None:
                continue
            att = umnik_chat_store.save_server_file(thread, src, raw, None)
            att.origin = UmnikChatAttachment.Origin.UMNIK
            att.save(update_fields=['origin'])
            added.append(att)
        umnik_chat_store.link_attachments(answer_msg, added)
        answer_attachments = [umnik_chat_store.serialize_attachment(a) for a in added]
        thread.refresh_from_db()
    status_code = 200 if result.get('ok') else 502
    return JsonResponse(
        {
            **result,
            'answer': answer,
            'thread': umnik_chat_store.serialize_thread(thread),
            'user_attachments': [umnik_chat_store.serialize_attachment(a) for a in atts],
            'answer_attachments': answer_attachments,
        },
        status=status_code,
    )


class DealCreateView(LoginRequiredMixin, FormView):
    template_name = 'deal_form.html'
    form_class = DealCreateForm

    def form_valid(self, form):
        deal = form.save(commit=False)
        deal.margin_percent = get_default_margin_percent()
        new_client_name = form.cleaned_data.get('new_client_name', '').strip()
        if new_client_name and not deal.client:
            parsed = parse_quick_client_name(new_client_name)
            if parsed:
                lookup = {k: parsed[k] for k in ('company_name', 'last_name', 'first_name', 'middle_name')}
                client, _ = Client.objects.get_or_create(
                    **lookup,
                    defaults={'created_by': self.request.user},
                )
                deal.client = client
        deal.save()
        ensure_deal_dirs(deal)
        return redirect('deal_detail', pk=deal.pk)


@login_required
@require_POST
def create_dashboard_lead(request):
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    form = DashboardLeadForm(request.POST)
    if not form.is_valid():
        return render(request, 'includes/dashboard_lead_modal_body.html', {'lead_form': form}, status=400)

    site_name = form.cleaned_data['location'].strip()
    module_count = form.cleaned_data['module_count']
    code_person_name = form.cleaned_data['first_name'].strip()
    lead_project_code = build_project_code_from_parts(module_count, code_person_name, site_name)
    region_or_city = form.cleaned_data.get('region_or_city', '').strip()
    street = form.cleaned_data.get('street', '').strip()
    house_number = form.cleaned_data.get('house_number', '').strip()
    address_parts = []
    if region_or_city:
        address_parts.append(region_or_city)
    if street:
        address_parts.append(f'ул. {street}')
    if house_number:
        address_parts.append(f'д. {house_number}')
    address_text = ', '.join(address_parts)
    comment = (form.cleaned_data.get('comment') or '').strip()
    notes_parts = []
    if comment:
        notes_parts.append(comment)
    if address_text:
        notes_parts.append(f'Адрес: {address_text}')
    notes = '\n\n'.join(notes_parts)
    client = Client.objects.create(
        last_name=form.cleaned_data['last_name'].strip(),
        first_name=form.cleaned_data['first_name'].strip(),
        middle_name=(form.cleaned_data.get('middle_name') or '').strip(),
        company_name='',
        phone=form.cleaned_data['phone'],
        email=form.cleaned_data.get('email', ''),
        notes=notes,
        created_by=request.user,
    )
    client.set_portal_password(form.cleaned_data.get('portal_password', ''))
    client.save(update_fields=['portal_password_hash'])
    deal = Deal.objects.create(
        project_code=lead_project_code,
        code_client_name=code_person_name,
        code_site_name=site_name,
        module_count=module_count,
        client=client,
        status=Deal.Status.NEW,
        margin_percent=get_default_margin_percent(),
        mortgage_required=form.cleaned_data['mortgage_required'],
        target_deal_date=form.cleaned_data['target_deal_date'],
    )
    ensure_deal_dirs(deal)
    record_domain_event(
        actor=request.user,
        event_type='deal.created',
        entity_model='Deal',
        entity_id=deal.id,
        payload={
            'project_code': deal.project_code,
            'module_count': deal.module_count,
            'client_id': client.id,
        },
        request=request,
    )
    response = HttpResponse('')
    response['HX-Redirect'] = redirect('deal_detail', pk=deal.pk).url
    return response


@login_required
@require_POST
def update_deal_module_count(request, deal_id):
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    raw = request.POST.get('module_count', '').strip()
    if not raw.isdigit():
        return HttpResponseBadRequest('Invalid module_count')
    new_count = int(raw)
    if not 0 <= new_count <= 15:
        return HttpResponseBadRequest('Invalid module_count range')

    if deal.module_count != new_count:
        if not deal.code_client_name or not deal.code_site_name:
            return HttpResponseBadRequest('Deal code parts are missing')
        new_code = build_project_code_from_parts(new_count, deal.code_client_name, deal.code_site_name)
        normalized = normalize_project_code(new_code)
        conflict = Deal.objects.filter(project_code_normalized=normalized).exclude(pk=deal.pk).exists()
        if conflict:
            return HttpResponseBadRequest('Project code conflict')

        old_count = deal.module_count
        old_code = deal.project_code
        deal.module_count = new_count
        deal.project_code = new_code
        deal.save(update_fields=['module_count', 'project_code', 'updated_at'])
        ChangeLog.objects.create(
            project_version=_ensure_latest_version_for_log(deal, request.user),
            changed_by=request.user,
            field_path='module_count',
            old_value={'value': old_count, 'project_code': old_code},
            new_value={'value': new_count, 'project_code': new_code},
        )

    response = HttpResponse('')
    response['HX-Redirect'] = redirect('deal_detail', pk=deal.pk).url
    return response


def _normalize_upload_name(filename: str) -> str:
    safe = ''.join(ch for ch in filename if ch not in '/\\').strip()
    return safe or 'file.bin'


def _detect_category(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in {'.jpg', '.jpeg', '.png', '.webp', '.gif'}:
        return ProjectFile.Category.PHOTO
    if ext == '.pdf':
        return ProjectFile.Category.PDF
    if ext in {'.dwg', '.dxf'}:
        return ProjectFile.Category.DWG
    return ProjectFile.Category.OTHER


def _source_dir_by_category(source: str, category: str) -> Path:
    if source == ProjectFile.Source.CLIENT:
        if category == ProjectFile.Category.PHOTO:
            return Path('incoming/client/photos')
        return Path('incoming/client/docs')
    if source == ProjectFile.Source.DESIGNER:
        if category == ProjectFile.Category.PDF:
            return Path('incoming/designer/plans_pdf')
        if category == ProjectFile.Category.DWG:
            return Path('incoming/designer/dwg')
        return Path('incoming/designer/reference')
    if source == ProjectFile.Source.SALES:
        if category == ProjectFile.Category.PHOTO:
            return Path('incoming/sales/photos')
        return Path('incoming/sales/docs')
    return Path('system')


def _files_summary(deal, source: str):
    qs = deal.project_files.filter(source=source, is_archived=False).order_by('-updated_at')
    latest = qs.first()
    return {
        'items': qs,
        'latest': latest,
        'count': qs.count(),
    }


def _files_context(deal, viewer=None, **extra):
    can_client = can_access_file_source(viewer, ProjectFile.Source.CLIENT) if viewer else True
    can_designer = can_access_file_source(viewer, ProjectFile.Source.DESIGNER) if viewer else True
    can_sales = can_access_file_source(viewer, ProjectFile.Source.SALES) if viewer else True
    context = {
        'deal': deal,
        'can_view_client_files': can_client,
        'can_view_designer_files': can_designer,
        'can_view_sales_files': can_sales,
        'client_files': _files_summary(deal, ProjectFile.Source.CLIENT) if can_client else {'items': [], 'latest': None, 'count': 0},
        'designer_files': _files_summary(deal, ProjectFile.Source.DESIGNER) if can_designer else {'items': [], 'latest': None, 'count': 0},
        'sales_files': _files_summary(deal, ProjectFile.Source.SALES) if can_sales else {'items': [], 'latest': None, 'count': 0},
        'client_upload_form': DealFileUploadForm(initial={'source': ProjectFile.Source.CLIENT}) if can_client else None,
        'designer_upload_form': DealFileUploadForm(initial={'source': ProjectFile.Source.DESIGNER}) if can_designer else None,
        'sales_upload_form': DealFileUploadForm(initial={'source': ProjectFile.Source.SALES}) if can_sales else None,
    }
    context.update(extra)
    return context


def _archive_file(file_obj, user):
    abs_path = file_obj.absolute_path
    if abs_path.exists() and abs_path.is_file():
        archive_dir = get_deal_root(file_obj.deal) / 'archive'
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / abs_path.name
        if target.exists():
            target = archive_dir / f"{timezone.now().strftime('%Y%m%d_%H%M%S')}_{abs_path.name}"
        shutil.move(str(abs_path), str(target))
        file_obj.relative_path = str(target.relative_to(get_files_root())).replace('\\', '/')
    file_obj.is_archived = True
    file_obj.archived_at = timezone.now()
    file_obj.archived_by = user
    file_obj.save(update_fields=['relative_path', 'is_archived', 'archived_at', 'archived_by', 'updated_at'])


def _log_file_event(deal, user, action: str, file_obj=None, extra=None):
    payload = {
        'action': action,
    }
    if file_obj is not None:
        payload.update(
            {
                'file_id': file_obj.id,
                'file_name': file_obj.original_name,
                'source': file_obj.source,
                'category': file_obj.category,
            }
        )
    if extra:
        payload.update(extra)
    ChangeLog.objects.create(
        project_version=_ensure_latest_version_for_log(deal, user),
        changed_by=user,
        field_path='files.event',
        old_value=None,
        new_value=_json_ready(payload),
    )


@login_required
@require_POST
def upload_project_file(request, deal_id):
    deal = get_object_or_404(Deal, pk=deal_id)
    form = DealFileUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(
            request,
            'includes/deal_files_block.html',
            _files_context(deal, viewer=request.user, files_error='Не удалось загрузить файл.'),
            status=400,
        )

    source = form.cleaned_data['source']
    if not can_access_file_source(request.user, source):
        return HttpResponseForbidden('Not allowed')
    uploaded = form.cleaned_data['upload']
    ensure_deal_dirs(deal)
    category = _detect_category(uploaded.name)
    relative_dir = _source_dir_by_category(source, category)
    stamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    original_name = _normalize_upload_name(uploaded.name)
    ext = Path(original_name).suffix.lower().lstrip('.')
    filename = f'{stamp}_{source}_{category}_{original_name}'
    relative_path = get_deal_root(deal).joinpath(relative_dir, filename).relative_to(get_files_root())
    absolute_path = get_files_root() / relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    with absolute_path.open('wb+') as destination:
        for chunk in uploaded.chunks():
            destination.write(chunk)

    created_file = ProjectFile.objects.create(
        # Record upload in change history.
        deal=deal,
        source=source,
        category=category,
        relative_path=str(relative_path).replace('\\', '/'),
        original_name=original_name,
        size_bytes=uploaded.size,
        mime_type=mimetypes.guess_type(original_name)[0] or '',
        ext=ext,
        uploaded_by=request.user,
    )
    _log_file_event(deal, request.user, 'upload', created_file, {'size_bytes': uploaded.size})
    return render(
        request,
        'includes/deal_files_block.html',
        _files_context(deal, viewer=request.user, files_notice='Файл загружен.'),
    )


@login_required
@xframe_options_sameorigin
def open_project_file(request, file_id):
    file_obj = get_object_or_404(ProjectFile, pk=file_id, is_archived=False)
    if not can_access_file_source(request.user, file_obj.source):
        return HttpResponseForbidden('Not allowed')
    absolute_path = file_obj.absolute_path
    if not absolute_path.exists() or not absolute_path.is_file():
        raise Http404('File not found')
    if request.GET.get('log', '1') != '0':
        _log_file_event(file_obj.deal, request.user, 'download', file_obj)
    return FileResponse(absolute_path.open('rb'), as_attachment=False, filename=file_obj.original_name)


@login_required
@require_POST
def archive_project_file(request, file_id):
    file_obj = get_object_or_404(ProjectFile, pk=file_id, is_archived=False)
    if not can_access_file_source(request.user, file_obj.source):
        return HttpResponseForbidden('Not allowed')
    deal = file_obj.deal
    source = file_obj.source
    file_name = file_obj.original_name
    _archive_file(file_obj, request.user)
    _log_file_event(
        deal,
        request.user,
        'archive',
        None,
        {'file_id': file_id, 'file_name': file_name, 'source': source},
    )

    return render(
        request,
        'includes/deal_files_block.html',
        _files_context(deal, viewer=request.user, files_notice='Файл перемещён в архив.', focus_source=source),
    )


@login_required
@require_POST
def bulk_project_file_action(request, deal_id, source):
    deal = get_object_or_404(Deal, pk=deal_id)
    if source not in {ProjectFile.Source.CLIENT, ProjectFile.Source.DESIGNER, ProjectFile.Source.SALES}:
        return HttpResponseBadRequest('Invalid source')
    if not can_access_file_source(request.user, source):
        return HttpResponseForbidden('Not allowed')
    selected_ids = [int(v) for v in request.POST.getlist('selected_ids') if v.isdigit()]
    if not selected_ids:
        return render(
            request,
            'includes/deal_files_block.html',
            _files_context(deal, viewer=request.user, files_error='Выберите хотя бы один файл.'),
            status=400,
        )

    action = request.POST.get('action', '').strip()
    files_qs = ProjectFile.objects.filter(
        deal=deal,
        source=source,
        is_archived=False,
        id__in=selected_ids,
    ).order_by('-updated_at')

    if action == 'archive':
        count = 0
        for file_obj in files_qs:
            file_id = file_obj.id
            file_name = file_obj.original_name
            file_source = file_obj.source
            _archive_file(file_obj, request.user)
            _log_file_event(
                deal,
                request.user,
                'archive',
                None,
                {'file_id': file_id, 'file_name': file_name, 'source': file_source, 'bulk': True},
            )
            count += 1
        return render(
            request,
            'includes/deal_files_block.html',
            _files_context(deal, viewer=request.user, files_notice=f'В архив перемещено: {count}.'),
        )

    if action == 'preview':
        first = files_qs.first()
        if not first:
            return render(
                request,
                'includes/deal_files_block.html',
                _files_context(deal, viewer=request.user, files_error='Файлы не найдены.'),
                status=404,
            )
        _log_file_event(deal, request.user, 'preview', first, {'bulk': True})
        return open_project_file(request, first.id)

    if action == 'download':
        downloaded_ids = []
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for file_obj in files_qs:
                path = file_obj.absolute_path
                if path.exists() and path.is_file():
                    zf.write(path, arcname=file_obj.original_name)
                    downloaded_ids.append(file_obj.id)
        _log_file_event(
            deal,
            request.user,
            'download_zip',
            None,
            {'bulk': True, 'source': source, 'file_ids': downloaded_ids, 'count': len(downloaded_ids)},
        )
        memory_file.seek(0)
        response = HttpResponse(memory_file.read(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename=deal-{deal.id}-{source}-files.zip'
        return response

    return HttpResponseBadRequest('Invalid action')


def _get_or_create_draft_version(deal, user):
    draft = deal.versions.filter(status=deal.versions.model.Status.DRAFT).order_by('-version_number').first()
    if draft is None:
        draft = deal.create_new_version(source='manual', created_by=user)
    return draft


def _draft_config_initial(deal, user):
    draft = _get_or_create_draft_version(deal, user)
    config_inputs = (draft.frozen_data or {}).get('config_inputs', {})
    return draft, {
        'building_area': config_inputs.get('building_area', '120'),
        'living_area': config_inputs.get('living_area', '90'),
        'ceiling_height': config_inputs.get('ceiling_height', '2.7'),
        'floor_150_qty': config_inputs.get('floor_150_qty', '0'),
        'floor_200_qty': config_inputs.get('floor_200_qty', '120'),
        'floor_250_qty': config_inputs.get('floor_250_qty', '0'),
        'floor_laminate_qty': config_inputs.get('floor_laminate_qty', '90'),
        'floor_tile_qty': config_inputs.get('floor_tile_qty', '0'),
        'facade_planken_lm': config_inputs.get('facade_planken_lm', '0'),
        'facade_combined_lm': config_inputs.get('facade_combined_lm', '48'),
        'partition_double_lm': config_inputs.get('partition_double_lm', '24'),
        'partition_single_lm': config_inputs.get('partition_single_lm', '16'),
        'finish_quarter_lm': config_inputs.get('finish_quarter_lm', '0'),
        'finish_ldsp_lm': config_inputs.get('finish_ldsp_lm', '48'),
        'finish_gkl_lm': config_inputs.get('finish_gkl_lm', '0'),
        'finish_mdf_lm': config_inputs.get('finish_mdf_lm', '0'),
        'finish_plywood_lm': config_inputs.get('finish_plywood_lm', '0'),
        'bathroom_tile_lm': config_inputs.get('bathroom_tile_lm', '0'),
        'roof_gable_qty': config_inputs.get('roof_gable_qty', '120'),
        'roof_flat_qty': config_inputs.get('roof_flat_qty', '0'),
        'interior_doors_count': config_inputs.get('interior_doors_count', 5),
        'windows_count': config_inputs.get('windows_count', 8),
        'windows_total_cost': config_inputs.get('windows_total_cost', '0'),
        'panoramic_sections_count': config_inputs.get('panoramic_sections_count', 0),
        'panoramic_sections_total_cost': config_inputs.get('panoramic_sections_total_cost', '0'),
        'sauna_cost': config_inputs.get('sauna_cost', '0'),
        'sauna_installation_cost': config_inputs.get('sauna_installation_cost', '0'),
        'bathrooms_count': config_inputs.get('bathrooms_count', 1),
    }


def _json_ready(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    return value


def _parse_decimal(raw_value):
    try:
        value = Decimal(str(raw_value).replace(',', '.'))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if value < 0:
        return None
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _bathrooms_button_enabled_for_form(form, frozen_data):
    """Кнопка активна по текущему значению D37 в форме (даже до сохранения)."""
    raw_count = None
    if getattr(form, 'is_bound', False):
        raw_count = form.data.get(form.add_prefix('bathrooms_count'))
    else:
        raw_count = form.initial.get('bathrooms_count')
    try:
        current_count = int(Decimal(str(raw_count).replace(',', '.')))
    except (InvalidOperation, ValueError, TypeError):
        current_count = 0
    if current_count >= 1:
        return True
    return bathrooms_button_enabled(frozen_data or {})


def _recalc_draft_calculation(deal, draft):
    """Пересчитать смету в draft по сохранённым config_inputs и строкам санузлов."""
    inputs = (draft.frozen_data or {}).get('config_inputs')
    if not inputs:
        return
    calc = calculate_config(inputs, margin_percent=deal.margin_percent, version=draft)
    frozen = draft.frozen_data or {}
    frozen['calculation'] = _json_ready(calc)
    frozen['saved_at'] = timezone.now().isoformat()
    draft.frozen_data = frozen
    draft.save(update_fields=['frozen_data'])


@login_required
@require_POST
def update_deal_cost_summary(request, deal_id):
    if not CONFIGURATOR_ENABLED:
        return _configurator_disabled_response(request, deal_id)
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    draft = _get_or_create_draft_version(deal, request.user)
    frozen = draft.frozen_data or {}
    calculation = frozen.get('calculation') or {}
    totals = dict(calculation.get('totals') or {})

    materials_total = _parse_decimal(request.POST.get('materials_total'))
    work_total = _parse_decimal(request.POST.get('work_total'))
    if None in {materials_total, work_total}:
        return HttpResponseBadRequest('Invalid totals payload')

    subtotal = (materials_total + work_total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    margin_multiplier = Decimal('1.00') + (Decimal(str(deal.margin_percent)) / Decimal('100.00'))
    with_margin = (subtotal * margin_multiplier).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    old_totals = {
        'material_total': totals.get('material_total'),
        'work_total': totals.get('work_total'),
        'subtotal': totals.get('subtotal'),
        'with_margin': totals.get('with_margin'),
    }
    totals.update(
        {
            'material_total': materials_total,
            'work_total': work_total,
            'subtotal': subtotal,
            'with_margin': with_margin,
            'margin_percent': deal.margin_percent,
        }
    )
    calculation['totals'] = totals
    frozen['calculation'] = _json_ready(calculation)
    frozen['saved_at'] = timezone.now().isoformat()
    draft.frozen_data = frozen
    draft.save(update_fields=['frozen_data'])
    ChangeLog.objects.create(
        project_version=draft,
        changed_by=request.user,
        field_path='cost_summary_manual_edit',
        old_value=_json_ready(old_totals),
        new_value=_json_ready(
            {
                'material_total': materials_total,
                'work_total': work_total,
                'subtotal': subtotal,
                'with_margin': with_margin,
            }
        ),
    )

    target_url = redirect('deal_detail', pk=deal.pk).url
    if request.headers.get('HX-Request') == 'true':
        response = HttpResponse('')
        response['HX-Redirect'] = target_url
        return response
    return redirect(target_url)


@login_required
def cost_summary_page(request, deal_id):
    if not CONFIGURATOR_ENABLED:
        return _configurator_disabled_response(request, deal_id)
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    draft, initial = _draft_config_initial(deal, request.user)
    frozen = draft.frozen_data or {}
    save_success = False
    archicad_notice = ''

    if request.method == 'POST':
        action = request.POST.get('action', '').strip()
        if action == 'upload_archicad':
            config_form = DealConfiguratorForm(initial=initial)
            calc_result = frozen.get('calculation') or calculate_config(
                config_form.initial, margin_percent=deal.margin_percent, version=draft
            )
            archicad_notice = 'Кнопка-заглушка: интеграция Archicad будет добавлена следующим шагом.'
        else:
            config_form = DealConfiguratorForm(request.POST)
            calc_result = None
            if config_form.is_valid():
                new_inputs = config_form.cleaned_data
                calc_result = calculate_config(new_inputs, margin_percent=deal.margin_percent, version=draft)
                if action == 'save':
                    old_inputs = (draft.frozen_data or {}).get('config_inputs', {})
                    changed_keys = [key for key in new_inputs.keys() if str(old_inputs.get(key, '')) != str(new_inputs.get(key, ''))]
                    draft.frozen_data = {
                        'calc_schema_version': CALC_SCHEMA_VERSION,
                        'config_inputs': _json_ready(new_inputs),
                        'saved_at': timezone.now().isoformat(),
                    }
                    draft.save(update_fields=['frozen_data'])
                    ensure_bathrooms(draft, bathrooms_count_from_config(draft.frozen_data))
                    calc_result = calculate_config(new_inputs, margin_percent=deal.margin_percent, version=draft)
                    fd = draft.frozen_data or {}
                    fd['calculation'] = _json_ready(calc_result)
                    fd['saved_at'] = timezone.now().isoformat()
                    draft.frozen_data = fd
                    draft.save(update_fields=['frozen_data'])
                    for key in changed_keys:
                        ChangeLog.objects.create(
                            project_version=draft,
                            changed_by=request.user,
                            field_path=f'config.{key}',
                            old_value={'value': _json_ready(old_inputs.get(key))},
                            new_value={'value': _json_ready(new_inputs.get(key))},
                        )
                    save_success = True
            else:
                calc_result = None
    else:
        config_form = DealConfiguratorForm(initial=initial)
        calc_result = frozen.get('calculation')
        if calc_result is None:
            calc_result = calculate_config(config_form.initial, margin_percent=deal.margin_percent, version=draft)

    bathroom_material_total, bathroom_work_total = bathrooms_totals(draft)
    return render(
        request,
        'deal_cost_summary.html',
        {
            'deal': deal,
            'draft_version': draft,
            'config_form': config_form,
            'calc_result': calc_result,
            'save_success': save_success,
            'archicad_notice': archicad_notice,
            'bathrooms_button_enabled': _bathrooms_button_enabled_for_form(config_form, draft.frozen_data or {}),
            'bathroom_material_total': bathroom_material_total,
            'bathroom_work_total': bathroom_work_total,
            'bathroom_grand_total': bathroom_material_total + bathroom_work_total,
        },
    )


@login_required
@require_POST
def recalc_configurator(request, deal_id):
    if not CONFIGURATOR_ENABLED:
        return _configurator_disabled_response(request, deal_id)
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    form = DealConfiguratorForm(request.POST)
    calc_result = None
    draft = _get_or_create_draft_version(deal, request.user)
    if form.is_valid():
        ensure_bathrooms(draft, bathrooms_count_from_config({'config_inputs': form.cleaned_data}))
        calc_result = calculate_config(form.cleaned_data, margin_percent=deal.margin_percent, version=draft)
    bathroom_material_total, bathroom_work_total = bathrooms_totals(draft)
    return render(
        request,
        'includes/configurator_block.html',
        {
            'deal': deal,
            'config_form': form,
            'calc_result': calc_result,
            'draft_version': draft,
            'save_success': False,
            'bathrooms_button_enabled': _bathrooms_button_enabled_for_form(form, draft.frozen_data or {}),
            'bathroom_material_total': bathroom_material_total,
            'bathroom_work_total': bathroom_work_total,
            'bathroom_grand_total': bathroom_material_total + bathroom_work_total,
        },
        status=200 if form.is_valid() else 400,
    )


@login_required
@require_POST
def save_configurator_draft(request, deal_id):
    if not CONFIGURATOR_ENABLED:
        return _configurator_disabled_response(request, deal_id)
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    form = DealConfiguratorForm(request.POST)
    draft = _get_or_create_draft_version(deal, request.user)
    if not form.is_valid():
        return render(
            request,
            'includes/configurator_block.html',
            {
                'deal': deal,
                'config_form': form,
                'calc_result': None,
                'draft_version': draft,
                'save_success': False,
                'bathrooms_button_enabled': _bathrooms_button_enabled_for_form(form, draft.frozen_data or {}),
            },
            status=400,
        )

    new_inputs = form.cleaned_data
    old_inputs = (draft.frozen_data or {}).get('config_inputs', {})
    changed_keys = [key for key in new_inputs.keys() if str(old_inputs.get(key, '')) != str(new_inputs.get(key, ''))]

    draft.frozen_data = {
        'calc_schema_version': CALC_SCHEMA_VERSION,
        'config_inputs': _json_ready(new_inputs),
        'saved_at': timezone.now().isoformat(),
    }
    draft.save(update_fields=['frozen_data'])
    ensure_bathrooms(draft, bathrooms_count_from_config(draft.frozen_data))
    calc_result = calculate_config(new_inputs, margin_percent=deal.margin_percent, version=draft)
    fd = draft.frozen_data or {}
    fd['calculation'] = _json_ready(calc_result)
    fd['saved_at'] = timezone.now().isoformat()
    draft.frozen_data = fd
    draft.save(update_fields=['frozen_data'])

    for key in changed_keys:
        ChangeLog.objects.create(
            project_version=draft,
            changed_by=request.user,
            field_path=f'config.{key}',
            old_value={'value': _json_ready(old_inputs.get(key))},
            new_value={'value': _json_ready(new_inputs.get(key))},
        )

    bathroom_material_total, bathroom_work_total = bathrooms_totals(draft)
    return render(
        request,
        'includes/configurator_block.html',
        {
            'deal': deal,
            'config_form': form,
            'calc_result': calc_result,
            'draft_version': draft,
            'save_success': True,
            'bathrooms_button_enabled': _bathrooms_button_enabled_for_form(form, draft.frozen_data or {}),
            'bathroom_material_total': bathroom_material_total,
            'bathroom_work_total': bathroom_work_total,
            'bathroom_grand_total': bathroom_material_total + bathroom_work_total,
        },
    )


def _build_bathroom_tabs_context(deal, draft, count_override=None):
    """Контекст страницы вкладок санузлов."""
    count = count_override if count_override is not None else bathrooms_count_from_config(draft.frozen_data or {})
    ensure_bathrooms(draft, count)
    bathrooms = list(DealBathroom.objects.filter(project_version=draft).order_by('index'))
    formsets_by_id = {br.id: BathroomLineFormSet(instance=br) for br in bathrooms}
    bathroom_tabs = []
    for br in bathrooms:
        material_total, work_total, subtotal = bathroom_totals(br)
        bathroom_tabs.append(
            {
                'bathroom': br,
                'formset': formsets_by_id[br.id],
                'material_total': material_total,
                'work_total': work_total,
                'subtotal': subtotal,
            }
        )
    mat_tot, work_tot = bathrooms_totals(draft)
    return {
        'deal': deal,
        'draft_version': draft,
        'bathrooms': bathrooms,
        'bathroom_tabs': bathroom_tabs,
        'formsets_by_id': formsets_by_id,
        'template_section': get_template_section(),
        'material_total_all': mat_tot,
        'work_total_all': work_tot,
        'grand_total_all': mat_tot + work_tot,
        'option_unit_choices_ru': COST_ITEM_UNIT_CHOICES_RU,
    }


def _build_additional_options_context(deal, draft):
    ensure_additional_option_lines(draft)
    formset = AdditionalOptionLineFormSet(instance=draft)
    material_total, work_total = additional_options_totals(draft)
    return {
        'deal': deal,
        'draft_version': draft,
        'formset': formset,
        'create_form': AdditionalOptionCreateForm(),
        'material_total': material_total,
        'work_total': work_total,
        'grand_total': material_total + work_total,
    }


@login_required
def bathrooms_page(request, deal_id):
    if not CONFIGURATOR_ENABLED:
        return _configurator_disabled_response(request, deal_id)
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    draft = _get_or_create_draft_version(deal, request.user)
    count = bathrooms_count_from_config(draft.frozen_data or {})
    raw_count_qs = request.GET.get('count')
    if raw_count_qs not in (None, ''):
        try:
            count = int(Decimal(str(raw_count_qs)))
        except (InvalidOperation, ValueError, TypeError):
            pass
    if count < 1:
        _draft, initial = _draft_config_initial(deal, request.user)
        try:
            count = int(Decimal(str(initial.get('bathrooms_count', 0))))
        except (InvalidOperation, ValueError, TypeError):
            count = 0
    if count < 1:
        return redirect('deal_cost_summary_page', deal_id=deal.id)

    frozen = draft.frozen_data or {}
    config_inputs = dict(frozen.get('config_inputs') or {})
    if str(config_inputs.get('bathrooms_count')) != str(count):
        config_inputs['bathrooms_count'] = count
        frozen['config_inputs'] = config_inputs
        draft.frozen_data = frozen
        draft.save(update_fields=['frozen_data'])

    ensure_bathrooms(draft, count)
    ctx = _build_bathroom_tabs_context(deal, draft, count_override=count)
    return render(request, 'deal_bathrooms.html', ctx)


@login_required
@require_POST
def save_bathroom_tab(request, deal_id, bathroom_id):
    if not CONFIGURATOR_ENABLED:
        return _configurator_disabled_response(request, deal_id)
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    draft = _get_or_create_draft_version(deal, request.user)
    bathroom = DealBathroom.objects.filter(pk=bathroom_id, deal_id=deal.id, project_version=draft).first()
    if bathroom is None:
        # Пользователь мог отправить "протухшую" вкладку (id из старой страницы после изменения draft).
        count = bathrooms_count_from_config(draft.frozen_data or {})
        if count < 1:
            _d, initial = _draft_config_initial(deal, request.user)
            try:
                count = int(Decimal(str(initial.get('bathrooms_count', 0))))
            except (InvalidOperation, ValueError, TypeError):
                count = 0
        if count > 0:
            ensure_bathrooms(draft, count)
        return redirect(reverse('deal_bathrooms_page', kwargs={'deal_id': deal.id}) + '?stale=1')
    formset = BathroomLineFormSet(request.POST, instance=bathroom)
    if formset.is_valid():
        instances = formset.save(commit=False)
        for form in formset.forms:
            if not form.cleaned_data:
                continue
            obj = form.instance
            if 'selected_option' in form.changed_data and obj.selected_option_id:
                opt = obj.selected_option
                if opt is not None and opt.price > Decimal('0'):
                    obj.unit_price = opt.price
        for obj in instances:
            obj.save()
        formset.save_m2m()
        _recalc_draft_calculation(deal, draft)
        return redirect(reverse('deal_bathrooms_page', kwargs={'deal_id': deal.id}) + f'?saved={bathroom.id}')

    ctx = _build_bathroom_tabs_context(deal, draft)
    ctx['formsets_by_id'][bathroom.id] = formset
    ctx['bathroom_tabs'] = [
        {'bathroom': br, 'formset': ctx['formsets_by_id'][br.id]} for br in ctx['bathrooms']
    ]
    ctx['form_error_bathroom_id'] = bathroom.id
    return render(request, 'deal_bathrooms.html', ctx, status=400)


@login_required
def additional_options_page(request, deal_id):
    if not CONFIGURATOR_ENABLED:
        return _configurator_disabled_response(request, deal_id)
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    draft = _get_or_create_draft_version(deal, request.user)
    ctx = _build_additional_options_context(deal, draft)
    if request.GET.get('saved'):
        ctx['saved'] = True
    return render(request, 'deal_additional_options.html', ctx)


@login_required
@require_POST
def save_additional_options(request, deal_id):
    if not CONFIGURATOR_ENABLED:
        return _configurator_disabled_response(request, deal_id)
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    draft = _get_or_create_draft_version(deal, request.user)
    ensure_additional_option_lines(draft)
    formset = AdditionalOptionLineFormSet(request.POST, instance=draft)
    if formset.is_valid():
        formset.save()
        _recalc_draft_calculation(deal, draft)
        return redirect(reverse('deal_additional_options_page', kwargs={'deal_id': deal.id}) + '?saved=1')
    ctx = _build_additional_options_context(deal, draft)
    ctx['formset'] = formset
    return render(request, 'deal_additional_options.html', ctx, status=400)


@login_required
@require_POST
def create_additional_option(request, deal_id):
    if not CONFIGURATOR_ENABLED:
        return _configurator_disabled_response(request, deal_id)
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    draft = _get_or_create_draft_version(deal, request.user)
    ensure_additional_option_lines(draft)
    form = AdditionalOptionCreateForm(request.POST)
    if form.is_valid():
        from .models import DealAdditionalOptionLine

        max_so = (
            DealAdditionalOptionLine.objects.filter(project_version=draft).order_by('-sort_order').values_list('sort_order', flat=True).first() or 0
        )
        DealAdditionalOptionLine.objects.create(
            project_version=draft,
            cost_item_id=None,
            name_snapshot=form.cleaned_data['name'],
            kind='material',
            is_included=form.cleaned_data['is_included'],
            quantity=form.cleaned_data['quantity'],
            unit_price=form.cleaned_data['unit_price'],
            unit_snapshot=form.cleaned_data['unit'],
            sort_order=max_so + 10,
        )
        _recalc_draft_calculation(deal, draft)
        return redirect(reverse('deal_additional_options_page', kwargs={'deal_id': deal.id}) + '?saved=1')
    ctx = _build_additional_options_context(deal, draft)
    ctx['create_form'] = form
    return render(request, 'deal_additional_options.html', ctx, status=400)


# Параметры раздела «Электрика» — хранятся в draft.frozen_data['electrical'].
_ELECTRICAL_FIELDS = [
    ('input_power_kw', 'Вводная мощность, кВт', 'text'),
    ('phases', 'Количество фаз (1 / 3)', 'text'),
    ('input_type', 'Ввод (воздушный / кабельный, сечение СИП / кабеля)', 'text'),
    ('panel_location', 'Место установки щита', 'text'),
    ('panel_modules', 'Модулей в щите / резерв', 'text'),
    ('sockets_count', 'Розеток, шт', 'text'),
    ('switches_count', 'Выключателей, шт', 'text'),
    ('light_points', 'Точек освещения, шт', 'text'),
    ('lowcurrent', 'Слаботочка (интернет, ТВ, видеонаблюдение, домофон)', 'textarea'),
    ('grounding', 'Заземление, УЗО, молниезащита', 'textarea'),
    ('panel_scheme', 'Схема щита: группы, автоматы, номиналы', 'textarea'),
    ('notes', 'Прочие заметки по электрике', 'textarea'),
]


@login_required
def deal_electrical_page(request, deal_id):
    """Страница по проекту для пункта согласования «Электрика»."""
    if not CONFIGURATOR_ENABLED:
        return _configurator_disabled_response(request, deal_id)
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    draft = _get_or_create_draft_version(deal, request.user)
    stored = dict((draft.frozen_data or {}).get('electrical') or {})
    fields = [
        {'name': name, 'label': label, 'widget': widget, 'value': stored.get(name, '')}
        for name, label, widget in _ELECTRICAL_FIELDS
    ]
    approval = deal.approvals.filter(slug='electrical').first()
    return render(
        request,
        'deal_electrical.html',
        {
            'deal': deal,
            'draft_version': draft,
            'fields': fields,
            'approval': approval,
            'saved': request.GET.get('saved') == '1',
            'updated_at': stored.get('updated_at'),
            'updated_by': stored.get('updated_by'),
        },
    )


@login_required
@require_POST
def save_deal_electrical(request, deal_id):
    if not CONFIGURATOR_ENABLED:
        return _configurator_disabled_response(request, deal_id)
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    draft = _get_or_create_draft_version(deal, request.user)
    frozen = draft.frozen_data or {}
    data = {name: (request.POST.get(name) or '').strip() for name, _label, _widget in _ELECTRICAL_FIELDS}
    data['updated_at'] = timezone.now().isoformat()
    data['updated_by'] = request.user.get_username()
    frozen['electrical'] = data
    draft.frozen_data = frozen
    draft.save(update_fields=['frozen_data'])
    record_domain_event(
        actor=request.user,
        event_type='deal.electrical_updated',
        entity_model='Deal',
        entity_id=deal.id,
        payload={'deal_id': deal.id},
        request=request,
    )
    return redirect(reverse('deal_electrical_page', kwargs={'deal_id': deal.id}) + '?saved=1')


@login_required
@require_POST
def claim_lead(request, deal_id):
    deal = get_object_or_404(Deal, pk=deal_id, assigned_manager__isnull=True, status__in=[Deal.Status.ORPHAN, Deal.Status.NEW])
    deal.assigned_manager = request.user
    deal.save(update_fields=['assigned_manager', 'updated_at'])
    new_leads = (
        Deal.objects.select_related('client')
        .filter(assigned_manager__isnull=True, status__in=[Deal.Status.ORPHAN, Deal.Status.NEW])
        .order_by('-created_at')
    )
    return render(request, 'includes/dashboard_leads_block.html', {'new_leads': new_leads})


CLIENT_PORTAL_COOKIE = 'client_portal_token'


def _client_portal_context(deal, *, notice=None, error=None, email=None):
    return {
        'deal': deal,
        'notice': notice,
        'error': error,
        'email': email or '',
    }


def _require_client_portal_session(request, deal):
    token = request.COOKIES.get(CLIENT_PORTAL_COOKIE, '')
    session = get_portal_session(deal=deal, token=token)
    if session is None:
        return None, redirect(reverse('client_portal_entry', kwargs={'deal_id': deal.id}))
    touch_session(session)
    return session, None


def client_portal_entry(request, deal_id):
    deal = get_object_or_404(Deal.objects.select_related('client'), pk=deal_id)
    return render(request, 'client_portal/entry.html', _client_portal_context(deal))


@require_POST
def client_portal_send_otp(request, deal_id):
    deal = get_object_or_404(Deal.objects.select_related('client'), pk=deal_id)
    email = (request.POST.get('email') or '').strip()
    password = (request.POST.get('password') or '').strip()
    client = deal.client
    if client is None:
        return render(
            request,
            'client_portal/entry.html',
            _client_portal_context(deal, error='Клиент не привязан к сделке.', email=email),
            status=400,
        )
    if email.lower() != (client.email or '').strip().lower():
        return render(
            request,
            'client_portal/entry.html',
            _client_portal_context(deal, error='Неверный email или пароль.', email=email),
            status=400,
        )
    if not client.check_portal_password(password):
        return render(
            request,
            'client_portal/entry.html',
            _client_portal_context(deal, error='Неверный email или пароль.', email=email),
            status=400,
        )
    token = create_portal_session(deal=deal, email=email)
    response = redirect(reverse('client_portal_chat', kwargs={'deal_id': deal.id}))
    response.set_cookie(
        CLIENT_PORTAL_COOKIE,
        token,
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        secure=getattr(request, 'is_secure', lambda: False)(),
        samesite='Lax',
    )
    return response


def client_portal_chat(request, deal_id):
    deal = get_object_or_404(Deal.objects.select_related('client'), pk=deal_id)
    session, redirect_response = _require_client_portal_session(request, deal)
    if redirect_response:
        return redirect_response
    messages = (
        DealClientMessage.objects.filter(deal=deal)
        .select_related('author_user')
        .prefetch_related('attachments', 'attachments__project_file')
        .order_by('created_at')[:200]
    )
    return render(
        request,
        'client_portal/chat.html',
        {
            'deal': deal,
            'session_email': session.email,
            'messages': messages,
        },
    )


@require_POST
def client_portal_message_send(request, deal_id):
    deal = get_object_or_404(Deal, pk=deal_id)
    session, redirect_response = _require_client_portal_session(request, deal)
    if redirect_response:
        return redirect_response
    body = (request.POST.get('body') or '').strip()
    if not body:
        return redirect(reverse('client_portal_chat', kwargs={'deal_id': deal.id}))
    DealClientMessage.objects.create(
        deal=deal,
        author_type=DealClientMessage.AuthorType.CLIENT,
        author_user=None,
        author_email=session.email,
        body=body,
    )
    return redirect(reverse('client_portal_chat', kwargs={'deal_id': deal.id}))


def _save_portal_upload_as_project_file(*, deal, uploaded, relative_dir: Path, source: str):
    ensure_deal_dirs(deal)
    stamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    original_name = _normalize_upload_name(uploaded.name)
    ext = Path(original_name).suffix.lower().lstrip('.')
    filename = f'{stamp}_{source}_other_{original_name}'
    relative_path = get_deal_root(deal).joinpath(relative_dir, filename).relative_to(get_files_root())
    absolute_path = get_files_root() / relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    with absolute_path.open('wb+') as destination:
        for chunk in uploaded.chunks():
            destination.write(chunk)

    return ProjectFile.objects.create(
        deal=deal,
        source=source,
        category=ProjectFile.Category.OTHER,
        relative_path=str(relative_path).replace('\\', '/'),
        original_name=original_name,
        size_bytes=uploaded.size,
        mime_type=getattr(uploaded, 'content_type', '') or mimetypes.guess_type(original_name)[0] or '',
        ext=ext,
        uploaded_by=None,
    )


@require_POST
def client_portal_upload(request, deal_id):
    deal = get_object_or_404(Deal, pk=deal_id)
    session, redirect_response = _require_client_portal_session(request, deal)
    if redirect_response:
        return redirect_response

    uploaded = request.FILES.get('upload')
    if not uploaded:
        return redirect(reverse('client_portal_chat', kwargs={'deal_id': deal.id}))

    content_type = (getattr(uploaded, 'content_type', '') or '').lower()
    is_voice = content_type.startswith('audio/')
    relative_dir = Path('incoming/client/voice' if is_voice else 'incoming/client/docs')
    pf = _save_portal_upload_as_project_file(deal=deal, uploaded=uploaded, relative_dir=relative_dir, source=ProjectFile.Source.CLIENT)

    msg = DealClientMessage.objects.create(
        deal=deal,
        author_type=DealClientMessage.AuthorType.CLIENT,
        author_user=None,
        author_email=session.email,
        body='' if is_voice else f'Файл: {pf.original_name}',
    )
    DealClientMessageAttachment.objects.create(
        message=msg,
        kind=DealClientMessageAttachment.Kind.VOICE if is_voice else DealClientMessageAttachment.Kind.PROJECT_FILE,
        project_file=pf,
        mime_type=pf.mime_type,
        duration_ms=None,
    )
    return redirect(reverse('client_portal_chat', kwargs={'deal_id': deal.id}))


def client_portal_open_project_file(request, deal_id, file_id):
    deal = get_object_or_404(Deal, pk=deal_id)
    session, redirect_response = _require_client_portal_session(request, deal)
    if redirect_response:
        return redirect_response
    file_obj = get_object_or_404(ProjectFile, pk=file_id, deal=deal, is_archived=False)
    absolute_path = file_obj.absolute_path
    if not absolute_path.exists() or not absolute_path.is_file():
        raise Http404('File not found')
    # Do not log client downloads into staff change log for now.
    return FileResponse(absolute_path.open('rb'), as_attachment=False, filename=file_obj.original_name)


@login_required
@require_POST
def deal_client_message_send(request, deal_id):
    deal = get_object_or_404(Deal, pk=deal_id)
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    body = (request.POST.get('body') or '').strip()
    if not body:
        return redirect('deal_detail', pk=deal.id)
    message = DealClientMessage.objects.create(
        deal=deal,
        author_type=DealClientMessage.AuthorType.STAFF,
        author_user=request.user,
        author_email='',
        body=body,
    )
    record_domain_event(
        actor=request.user,
        event_type='client_message.sent',
        entity_model='DealClientMessage',
        entity_id=message.id,
        payload={'deal_id': deal.id, 'kind': 'text'},
        request=request,
    )
    return redirect('deal_detail', pk=deal.id)


@login_required
@require_POST
def deal_client_message_attach_existing(request, deal_id):
    deal = get_object_or_404(Deal, pk=deal_id)
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    raw_id = (request.POST.get('project_file_id') or '').strip()
    if not raw_id.isdigit():
        return redirect('deal_detail', pk=deal.id)
    pf = get_object_or_404(ProjectFile, pk=int(raw_id), deal=deal, is_archived=False)
    msg = DealClientMessage.objects.create(
        deal=deal,
        author_type=DealClientMessage.AuthorType.STAFF,
        author_user=request.user,
        author_email='',
        body=f'Файл: {pf.original_name}',
    )
    DealClientMessageAttachment.objects.create(
        message=msg,
        kind=DealClientMessageAttachment.Kind.PROJECT_FILE,
        project_file=pf,
        mime_type=pf.mime_type,
        duration_ms=None,
    )
    record_domain_event(
        actor=request.user,
        event_type='client_message.sent',
        entity_model='DealClientMessage',
        entity_id=msg.id,
        payload={'deal_id': deal.id, 'kind': 'project_file', 'project_file_id': pf.id},
        request=request,
    )
    return redirect('deal_detail', pk=deal.id)


@login_required
@require_POST
def deal_client_message_upload(request, deal_id):
    deal = get_object_or_404(Deal, pk=deal_id)
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    uploaded = request.FILES.get('upload')
    if not uploaded:
        return redirect('deal_detail', pk=deal.id)

    content_type = (getattr(uploaded, 'content_type', '') or '').lower()
    is_voice = content_type.startswith('audio/')
    relative_dir = Path('outgoing/client')
    pf = _save_portal_upload_as_project_file(
        deal=deal,
        uploaded=uploaded,
        relative_dir=relative_dir,
        source=ProjectFile.Source.SYSTEM,
    )
    pf.uploaded_by = request.user
    pf.save(update_fields=['uploaded_by'])

    msg = DealClientMessage.objects.create(
        deal=deal,
        author_type=DealClientMessage.AuthorType.STAFF,
        author_user=request.user,
        author_email='',
        body='' if is_voice else f'Файл: {pf.original_name}',
    )
    DealClientMessageAttachment.objects.create(
        message=msg,
        kind=DealClientMessageAttachment.Kind.VOICE if is_voice else DealClientMessageAttachment.Kind.PROJECT_FILE,
        project_file=pf,
        mime_type=pf.mime_type,
        duration_ms=None,
    )
    record_domain_event(
        actor=request.user,
        event_type='client_message.sent',
        entity_model='DealClientMessage',
        entity_id=msg.id,
        payload={
            'deal_id': deal.id,
            'kind': 'voice' if is_voice else 'uploaded_file',
            'project_file_id': pf.id,
        },
        request=request,
    )
    return redirect('deal_detail', pk=deal.id)


# ---------------------------------------------------------------------------
# Этап «Согласования»: чек-лист, версии, гейт этапа
# ---------------------------------------------------------------------------

def _render_approvals_block(request, deal):
    return render(request, 'includes/deal_approvals_block.html', build_approvals_context(deal))


@login_required
@require_GET
def deal_approvals(request, deal_id):
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    return _render_approvals_block(request, deal)


@login_required
@require_POST
def update_deal_approval(request, deal_id):
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    ensure_deal_approvals(deal)
    slug = (request.POST.get('slug') or '').strip()
    approval = deal.approvals.filter(slug=slug).first()
    if approval is None:
        return HttpResponseBadRequest('Unknown approval')

    new_status = (request.POST.get('status') or '').strip()
    valid_statuses = {value for value, _ in DealApproval.Status.choices}
    if new_status not in valid_statuses:
        return HttpResponseBadRequest('Invalid status')

    version = None
    raw_version = (request.POST.get('project_version') or '').strip()
    if raw_version.isdigit():
        version = deal.versions.filter(pk=int(raw_version)).first()

    old_status = approval.status
    approval.status = new_status
    approval.comment = (request.POST.get('comment') or '').strip()
    approval.project_version = version
    decided_statuses = {
        DealApproval.Status.APPROVED,
        DealApproval.Status.REJECTED,
        DealApproval.Status.NOT_REQUIRED,
    }
    if new_status in decided_statuses:
        approval.decided_by = request.user
        approval.decided_at = timezone.now()
    else:
        approval.decided_by = None
        approval.decided_at = None
    approval.save()

    if old_status != new_status:
        ChangeLog.objects.create(
            project_version=_ensure_latest_version_for_log(deal, request.user),
            changed_by=request.user,
            field_path=f'approval.{slug}',
            old_value={'value': old_status},
            new_value={'value': new_status},
        )
        record_domain_event(
            actor=request.user,
            event_type='deal.approval_changed',
            entity_model='DealApproval',
            entity_id=approval.id,
            payload={'deal_id': deal.id, 'slug': slug, 'status': new_status},
            request=request,
        )
    return _render_approvals_block(request, deal)


@login_required
@require_POST
def manage_deal_approval(request, deal_id):
    """Редактирование набора пунктов чек-листа: добавить/удалить/переключить обязательность."""
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    ensure_deal_approvals(deal)
    action = (request.POST.get('action') or '').strip()

    if action == 'add':
        title = (request.POST.get('title') or '').strip()
        if not title:
            return HttpResponseBadRequest('Empty title')
        base = slugify(title, allow_unicode=False) or 'item'
        base = f'custom-{base}'[:40]
        slug = base
        taken = set(deal.approvals.values_list('slug', flat=True))
        counter = 2
        while slug in taken:
            slug = f'{base}-{counter}'
            counter += 1
        last_order = deal.approvals.order_by('-sort_order').values_list('sort_order', flat=True).first() or 0
        DealApproval.objects.create(
            deal=deal,
            slug=slug,
            title=title[:200],
            hint=(request.POST.get('hint') or '').strip()[:300],
            is_required=request.POST.get('is_required') == 'on',
            is_custom=True,
            sort_order=last_order + 1,
        )
        record_domain_event(
            actor=request.user,
            event_type='deal.approval_item_added',
            entity_model='DealApproval',
            entity_id=deal.id,
            payload={'deal_id': deal.id, 'slug': slug},
            request=request,
        )
        return _render_approvals_block(request, deal)

    slug = (request.POST.get('slug') or '').strip()
    approval = deal.approvals.filter(slug=slug).first()
    if approval is None:
        return HttpResponseBadRequest('Unknown approval')

    if action == 'remove':
        if not approval.is_custom:
            return HttpResponseBadRequest('Cannot remove template item')
        approval.delete()
        record_domain_event(
            actor=request.user,
            event_type='deal.approval_item_removed',
            entity_model='DealApproval',
            entity_id=deal.id,
            payload={'deal_id': deal.id, 'slug': slug},
            request=request,
        )
    elif action == 'toggle_required':
        approval.is_required = not approval.is_required
        approval.save(update_fields=['is_required', 'updated_at'])
    else:
        return HttpResponseBadRequest('Unknown action')

    return _render_approvals_block(request, deal)


# Связанные полноценные страницы CRM для отдельных пунктов чек-листа.
_APPROVAL_RELATED_PAGES = {
    'layout': [('Смета и конфигуратор', 'deal_cost_summary_page')],
    'cost_quote': [('Смета и конфигуратор', 'deal_cost_summary_page')],
    'bathrooms': [('Комплектация санузлов', 'deal_bathrooms_page')],
    'additional_options': [('Дополнительные опции', 'deal_additional_options_page')],
    'finishing': [('Смета и конфигуратор', 'deal_cost_summary_page')],
    'electrical': [('Электрика — параметры проекта', 'deal_electrical_page')],
}


def _approval_related_links(deal, slug):
    links = []
    for label, url_name in _APPROVAL_RELATED_PAGES.get(slug, []):
        links.append({'label': label, 'url': reverse(url_name, kwargs={'deal_id': deal.id})})
    return links


@login_required
@require_GET
def deal_approval_detail(request, deal_id, slug):
    """Страница по проекту для одного пункта чек-листа согласований."""
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    ensure_deal_approvals(deal)
    approval = (
        deal.approvals.select_related('decided_by', 'project_version')
        .filter(slug=slug)
        .first()
    )
    if approval is None:
        raise Http404('Unknown approval')
    versions = list(deal.versions.order_by('-version_number'))
    history = (
        ChangeLog.objects.filter(project_version__deal=deal, field_path=f'approval.{slug}')
        .select_related('changed_by')
        .order_by('-changed_at')[:50]
    )
    attachments = list(
        approval.files.filter(is_archived=False)
        .select_related('uploaded_by')
        .order_by('-created_at')
    )
    return render(
        request,
        'deal_approval_detail.html',
        {
            'deal': deal,
            'approval': approval,
            'versions': versions,
            'approval_status_choices': DealApproval.Status.choices,
            'history': history,
            'related_links': _approval_related_links(deal, slug),
            'attachments': attachments,
            'file_error': request.GET.get('file_error') == '1',
            'saved': request.GET.get('saved') == '1',
        },
    )


@login_required
@require_POST
def save_deal_approval_detail(request, deal_id, slug):
    """Сохранение статуса, версии, комментария и рабочих заметок пункта чек-листа."""
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    ensure_deal_approvals(deal)
    approval = deal.approvals.filter(slug=slug).first()
    if approval is None:
        raise Http404('Unknown approval')

    new_status = (request.POST.get('status') or '').strip()
    valid_statuses = {value for value, _ in DealApproval.Status.choices}
    if new_status not in valid_statuses:
        return HttpResponseBadRequest('Invalid status')

    version = None
    raw_version = (request.POST.get('project_version') or '').strip()
    if raw_version.isdigit():
        version = deal.versions.filter(pk=int(raw_version)).first()

    old_status = approval.status
    approval.status = new_status
    approval.comment = (request.POST.get('comment') or '').strip()
    approval.notes = (request.POST.get('notes') or '').strip()
    approval.project_version = version
    decided_statuses = {
        DealApproval.Status.APPROVED,
        DealApproval.Status.REJECTED,
        DealApproval.Status.NOT_REQUIRED,
    }
    if new_status in decided_statuses:
        approval.decided_by = request.user
        approval.decided_at = timezone.now()
    else:
        approval.decided_by = None
        approval.decided_at = None
    approval.save()

    if old_status != new_status:
        ChangeLog.objects.create(
            project_version=_ensure_latest_version_for_log(deal, request.user),
            changed_by=request.user,
            field_path=f'approval.{slug}',
            old_value={'value': old_status},
            new_value={'value': new_status},
        )
        record_domain_event(
            actor=request.user,
            event_type='deal.approval_changed',
            entity_model='DealApproval',
            entity_id=approval.id,
            payload={'deal_id': deal.id, 'slug': slug, 'status': new_status},
            request=request,
        )
    return redirect(
        reverse('deal_approval_detail', kwargs={'deal_id': deal.id, 'slug': slug}) + '?saved=1'
    )


def _approval_detail_redirect(deal_id, slug, query=''):
    return redirect(
        reverse('deal_approval_detail', kwargs={'deal_id': deal_id, 'slug': slug}) + query
    )


@login_required
@require_POST
def upload_deal_approval_file(request, deal_id, slug):
    """Прикрепить файл-основание (PDF и др.) к пункту чек-листа согласований."""
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    ensure_deal_approvals(deal)
    approval = deal.approvals.filter(slug=slug).first()
    if approval is None:
        raise Http404('Unknown approval')

    uploaded = request.FILES.get('upload')
    if uploaded is None:
        return _approval_detail_redirect(deal.id, slug, '?file_error=1')

    ensure_deal_dirs(deal)
    category = _detect_category(uploaded.name)
    original_name = _normalize_upload_name(uploaded.name)
    ext = Path(original_name).suffix.lower().lstrip('.')
    stamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    relative_dir = Path('approvals') / slug
    filename = f'{stamp}_{original_name}'
    relative_path = get_deal_root(deal).joinpath(relative_dir, filename).relative_to(get_files_root())
    absolute_path = get_files_root() / relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    with absolute_path.open('wb+') as destination:
        for chunk in uploaded.chunks():
            destination.write(chunk)

    created_file = ProjectFile.objects.create(
        deal=deal,
        approval=approval,
        project_version=approval.project_version,
        source=ProjectFile.Source.SYSTEM,
        category=category,
        relative_path=str(relative_path).replace('\\', '/'),
        original_name=original_name,
        size_bytes=uploaded.size,
        mime_type=mimetypes.guess_type(original_name)[0] or '',
        ext=ext,
        uploaded_by=request.user,
    )
    _log_file_event(deal, request.user, 'upload', created_file, {'approval': slug, 'size_bytes': uploaded.size})
    record_domain_event(
        actor=request.user,
        event_type='deal.approval_file_added',
        entity_model='DealApproval',
        entity_id=approval.id,
        payload={'deal_id': deal.id, 'slug': slug, 'file_id': created_file.id, 'name': original_name},
        request=request,
    )
    return _approval_detail_redirect(deal.id, slug, '?saved=1')


@login_required
@xframe_options_sameorigin
@require_GET
def open_deal_approval_file(request, deal_id, file_id):
    """Отдать файл-основание пункта чек-листа для просмотра в браузере."""
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    file_obj = get_object_or_404(
        ProjectFile, pk=file_id, deal_id=deal_id, is_archived=False
    )
    if file_obj.approval_id is None:
        raise Http404('Not an approval file')
    absolute_path = file_obj.absolute_path
    if not absolute_path.exists() or not absolute_path.is_file():
        raise Http404('File not found')
    return FileResponse(absolute_path.open('rb'), as_attachment=False, filename=file_obj.original_name)


@login_required
@require_POST
def delete_deal_approval_file(request, deal_id, slug, file_id):
    """Убрать файл-основание из пункта чек-листа (в архив)."""
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    file_obj = get_object_or_404(
        ProjectFile, pk=file_id, deal=deal, is_archived=False
    )
    file_name = file_obj.original_name
    _archive_file(file_obj, request.user)
    _log_file_event(
        deal,
        request.user,
        'archive',
        None,
        {'file_id': file_id, 'file_name': file_name, 'approval': slug},
    )
    return _approval_detail_redirect(deal.id, slug, '?saved=1')


@login_required
@require_POST
def update_project_version_status(request, deal_id):
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    raw_version = (request.POST.get('version_id') or '').strip()
    action = (request.POST.get('action') or '').strip()
    if not raw_version.isdigit():
        return HttpResponseBadRequest('Invalid version')
    version = get_object_or_404(ProjectVersion, pk=int(raw_version), deal=deal)

    now = timezone.now()
    if action == 'send_to_client':
        version.status = ProjectVersion.Status.SENT_TO_CLIENT
        if version.quote_sent_at is None:
            version.quote_sent_at = now
        version.save(update_fields=['status', 'quote_sent_at'])
    elif action == 'client_accepted':
        (
            deal.versions.filter(status=ProjectVersion.Status.ACCEPTED)
            .exclude(pk=version.pk)
            .update(status=ProjectVersion.Status.SUPERSEDED)
        )
        version.status = ProjectVersion.Status.ACCEPTED
        version.save(update_fields=['status'])
    elif action == 'back_to_draft':
        version.status = ProjectVersion.Status.DRAFT
        version.save(update_fields=['status'])
    else:
        return HttpResponseBadRequest('Unknown action')

    ChangeLog.objects.create(
        project_version=version,
        changed_by=request.user,
        field_path='version.status',
        old_value=None,
        new_value={'value': version.status},
    )
    record_domain_event(
        actor=request.user,
        event_type='project_version.status_changed',
        entity_model='ProjectVersion',
        entity_id=version.id,
        payload={'deal_id': deal.id, 'status': version.status, 'action': action},
        request=request,
    )
    return _render_approvals_block(request, deal)


@login_required
@require_POST
def pass_approvals_stage(request, deal_id):
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    action = (request.POST.get('action') or 'pass').strip()
    items = ensure_deal_approvals(deal)
    gate = approvals_gate(items)
    accepted_version = (
        deal.versions.filter(status=ProjectVersion.Status.ACCEPTED)
        .order_by('-version_number')
        .first()
    )

    if action == 'reopen':
        if deal.approvals_passed_at is not None:
            deal.approvals_passed_at = None
            deal.save(update_fields=['approvals_passed_at', 'updated_at'])
            record_domain_event(
                actor=request.user,
                event_type='deal.approvals_reopened',
                entity_model='Deal',
                entity_id=deal.id,
                payload={'deal_id': deal.id},
                request=request,
            )
        return _render_approvals_block(request, deal)

    if not gate['passed'] or accepted_version is None:
        return HttpResponseBadRequest('Gate not passed')

    deal.approvals_passed_at = timezone.now()
    deal.save(update_fields=['approvals_passed_at', 'updated_at'])
    ChangeLog.objects.create(
        project_version=accepted_version,
        changed_by=request.user,
        field_path='approvals_passed_at',
        old_value=None,
        new_value={'value': deal.approvals_passed_at.isoformat()},
    )
    record_domain_event(
        actor=request.user,
        event_type='deal.approvals_passed',
        entity_model='Deal',
        entity_id=deal.id,
        payload={
            'deal_id': deal.id,
            'accepted_version': accepted_version.version_number,
        },
        request=request,
    )
    return _render_approvals_block(request, deal)


# ---------------------------------------------------------------------------
# Этап «Проектирование»: чек-лист разделов рабочей документации, гейт этапа
# ---------------------------------------------------------------------------

def _render_design_block(request, deal):
    return render(request, 'includes/deal_design_block.html', build_design_context(deal))


_DESIGN_DECIDED_STATUSES = {
    DealDesignSection.Status.RELEASED,
    DealDesignSection.Status.ON_HOLD,
    DealDesignSection.Status.NOT_REQUIRED,
}


@login_required
@require_GET
def deal_design(request, deal_id):
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    return _render_design_block(request, deal)


@login_required
@require_POST
def update_deal_design_section(request, deal_id):
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    ensure_deal_design_sections(deal)
    slug = (request.POST.get('slug') or '').strip()
    section = deal.design_sections.filter(slug=slug).first()
    if section is None:
        return HttpResponseBadRequest('Unknown design section')

    new_status = (request.POST.get('status') or '').strip()
    valid_statuses = {value for value, _ in DealDesignSection.Status.choices}
    if new_status not in valid_statuses:
        return HttpResponseBadRequest('Invalid status')

    version = None
    raw_version = (request.POST.get('project_version') or '').strip()
    if raw_version.isdigit():
        version = deal.versions.filter(pk=int(raw_version)).first()

    old_status = section.status
    section.status = new_status
    section.comment = (request.POST.get('comment') or '').strip()
    section.project_version = version
    if new_status in _DESIGN_DECIDED_STATUSES:
        section.decided_by = request.user
        section.decided_at = timezone.now()
    else:
        section.decided_by = None
        section.decided_at = None
    section.save()

    if old_status != new_status:
        ChangeLog.objects.create(
            project_version=_ensure_latest_version_for_log(deal, request.user),
            changed_by=request.user,
            field_path=f'design.{slug}',
            old_value={'value': old_status},
            new_value={'value': new_status},
        )
        record_domain_event(
            actor=request.user,
            event_type='deal.design_section_changed',
            entity_model='DealDesignSection',
            entity_id=section.id,
            payload={'deal_id': deal.id, 'slug': slug, 'status': new_status},
            request=request,
        )
    return _render_design_block(request, deal)


@login_required
@require_POST
def manage_deal_design_section(request, deal_id):
    """Добавить/удалить свой раздел или переключить обязательность."""
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    ensure_deal_design_sections(deal)
    action = (request.POST.get('action') or '').strip()

    if action == 'add':
        title = (request.POST.get('title') or '').strip()
        if not title:
            return HttpResponseBadRequest('Empty title')
        base = slugify(title, allow_unicode=False) or 'section'
        base = f'custom-{base}'[:40]
        slug = base
        taken = set(deal.design_sections.values_list('slug', flat=True))
        counter = 2
        while slug in taken:
            slug = f'{base}-{counter}'
            counter += 1
        last_order = deal.design_sections.order_by('-sort_order').values_list('sort_order', flat=True).first() or 0
        DealDesignSection.objects.create(
            deal=deal,
            slug=slug,
            title=title[:200],
            hint=(request.POST.get('hint') or '').strip()[:300],
            is_required=request.POST.get('is_required') == 'on',
            is_custom=True,
            sort_order=last_order + 1,
        )
        record_domain_event(
            actor=request.user,
            event_type='deal.design_section_added',
            entity_model='DealDesignSection',
            entity_id=deal.id,
            payload={'deal_id': deal.id, 'slug': slug},
            request=request,
        )
        return _render_design_block(request, deal)

    slug = (request.POST.get('slug') or '').strip()
    section = deal.design_sections.filter(slug=slug).first()
    if section is None:
        return HttpResponseBadRequest('Unknown design section')

    if action == 'remove':
        if not section.is_custom:
            return HttpResponseBadRequest('Cannot remove template section')
        section.delete()
        record_domain_event(
            actor=request.user,
            event_type='deal.design_section_removed',
            entity_model='DealDesignSection',
            entity_id=deal.id,
            payload={'deal_id': deal.id, 'slug': slug},
            request=request,
        )
    elif action == 'toggle_required':
        section.is_required = not section.is_required
        section.save(update_fields=['is_required', 'updated_at'])
    else:
        return HttpResponseBadRequest('Unknown action')

    return _render_design_block(request, deal)


_DESIGN_RELATED_PAGES = {
    'layout': [('Смета и конфигуратор', 'deal_cost_summary_page')],
    'openings': [('Смета и конфигуратор', 'deal_cost_summary_page')],
    'finishing': [('Смета и конфигуратор', 'deal_cost_summary_page')],
    'spec': [('Смета и конфигуратор', 'deal_cost_summary_page')],
    'electrical': [('Электрика — параметры проекта', 'deal_electrical_page')],
    'plumbing': [('Комплектация санузлов', 'deal_bathrooms_page')],
}


def _design_related_links(deal, slug):
    links = []
    for label, url_name in _DESIGN_RELATED_PAGES.get(slug, []):
        links.append({'label': label, 'url': reverse(url_name, kwargs={'deal_id': deal.id})})
    return links


@login_required
@require_GET
def deal_design_section_detail(request, deal_id, slug):
    """Страница по проекту для одного раздела рабочей документации."""
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    ensure_deal_design_sections(deal)
    section = (
        deal.design_sections.select_related('decided_by', 'project_version')
        .filter(slug=slug)
        .first()
    )
    if section is None:
        raise Http404('Unknown design section')
    versions = list(deal.versions.order_by('-version_number'))
    history = (
        ChangeLog.objects.filter(project_version__deal=deal, field_path=f'design.{slug}')
        .select_related('changed_by')
        .order_by('-changed_at')[:50]
    )
    attachments = list(
        section.files.filter(is_archived=False)
        .select_related('uploaded_by')
        .order_by('-created_at')
    )
    return render(
        request,
        'deal_design_section_detail.html',
        {
            'deal': deal,
            'section': section,
            'versions': versions,
            'design_status_choices': DealDesignSection.Status.choices,
            'history': history,
            'related_links': _design_related_links(deal, slug),
            'attachments': attachments,
            'file_error': request.GET.get('file_error') == '1',
            'saved': request.GET.get('saved') == '1',
        },
    )


@login_required
@require_POST
def save_deal_design_section_detail(request, deal_id, slug):
    """Сохранение статуса, версии, комментария и рабочих заметок раздела."""
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    ensure_deal_design_sections(deal)
    section = deal.design_sections.filter(slug=slug).first()
    if section is None:
        raise Http404('Unknown design section')

    new_status = (request.POST.get('status') or '').strip()
    valid_statuses = {value for value, _ in DealDesignSection.Status.choices}
    if new_status not in valid_statuses:
        return HttpResponseBadRequest('Invalid status')

    version = None
    raw_version = (request.POST.get('project_version') or '').strip()
    if raw_version.isdigit():
        version = deal.versions.filter(pk=int(raw_version)).first()

    old_status = section.status
    section.status = new_status
    section.comment = (request.POST.get('comment') or '').strip()
    section.notes = (request.POST.get('notes') or '').strip()
    section.project_version = version
    if new_status in _DESIGN_DECIDED_STATUSES:
        section.decided_by = request.user
        section.decided_at = timezone.now()
    else:
        section.decided_by = None
        section.decided_at = None
    section.save()

    if old_status != new_status:
        ChangeLog.objects.create(
            project_version=_ensure_latest_version_for_log(deal, request.user),
            changed_by=request.user,
            field_path=f'design.{slug}',
            old_value={'value': old_status},
            new_value={'value': new_status},
        )
        record_domain_event(
            actor=request.user,
            event_type='deal.design_section_changed',
            entity_model='DealDesignSection',
            entity_id=section.id,
            payload={'deal_id': deal.id, 'slug': slug, 'status': new_status},
            request=request,
        )
    return redirect(
        reverse('deal_design_section_detail', kwargs={'deal_id': deal.id, 'slug': slug}) + '?saved=1'
    )


def _design_detail_redirect(deal_id, slug, query=''):
    return redirect(
        reverse('deal_design_section_detail', kwargs={'deal_id': deal_id, 'slug': slug}) + query
    )


@login_required
@require_POST
def upload_deal_design_file(request, deal_id, slug):
    """Прикрепить файл (чертёж PDF и др.) к разделу рабочей документации."""
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    ensure_deal_design_sections(deal)
    section = deal.design_sections.filter(slug=slug).first()
    if section is None:
        raise Http404('Unknown design section')

    uploaded = request.FILES.get('upload')
    if uploaded is None:
        return _design_detail_redirect(deal.id, slug, '?file_error=1')

    ensure_deal_dirs(deal)
    category = _detect_category(uploaded.name)
    original_name = _normalize_upload_name(uploaded.name)
    ext = Path(original_name).suffix.lower().lstrip('.')
    stamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    relative_dir = Path('design') / slug
    filename = f'{stamp}_{original_name}'
    relative_path = get_deal_root(deal).joinpath(relative_dir, filename).relative_to(get_files_root())
    absolute_path = get_files_root() / relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    with absolute_path.open('wb+') as destination:
        for chunk in uploaded.chunks():
            destination.write(chunk)

    created_file = ProjectFile.objects.create(
        deal=deal,
        design_section=section,
        project_version=section.project_version,
        source=ProjectFile.Source.SYSTEM,
        category=category,
        relative_path=str(relative_path).replace('\\', '/'),
        original_name=original_name,
        size_bytes=uploaded.size,
        mime_type=mimetypes.guess_type(original_name)[0] or '',
        ext=ext,
        uploaded_by=request.user,
    )
    _log_file_event(deal, request.user, 'upload', created_file, {'design_section': slug, 'size_bytes': uploaded.size})
    record_domain_event(
        actor=request.user,
        event_type='deal.design_file_added',
        entity_model='DealDesignSection',
        entity_id=section.id,
        payload={'deal_id': deal.id, 'slug': slug, 'file_id': created_file.id, 'name': original_name},
        request=request,
    )
    return _design_detail_redirect(deal.id, slug, '?saved=1')


@login_required
@xframe_options_sameorigin
@require_GET
def open_deal_design_file(request, deal_id, file_id):
    """Отдать файл раздела рабочей документации для просмотра в браузере."""
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    file_obj = get_object_or_404(
        ProjectFile, pk=file_id, deal_id=deal_id, is_archived=False
    )
    if file_obj.design_section_id is None:
        raise Http404('Not a design file')
    absolute_path = file_obj.absolute_path
    if not absolute_path.exists() or not absolute_path.is_file():
        raise Http404('File not found')
    return FileResponse(absolute_path.open('rb'), as_attachment=False, filename=file_obj.original_name)


@login_required
@require_POST
def delete_deal_design_file(request, deal_id, slug, file_id):
    """Убрать файл из раздела рабочей документации (в архив)."""
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    file_obj = get_object_or_404(
        ProjectFile, pk=file_id, deal=deal, is_archived=False
    )
    file_name = file_obj.original_name
    _archive_file(file_obj, request.user)
    _log_file_event(
        deal,
        request.user,
        'archive',
        None,
        {'file_id': file_id, 'file_name': file_name, 'design_section': slug},
    )
    return _design_detail_redirect(deal.id, slug, '?saved=1')


@login_required
@require_POST
def pass_design_stage(request, deal_id):
    if is_file_only_role(request.user):
        return HttpResponseForbidden('Not allowed')
    deal = get_object_or_404(Deal, pk=deal_id)
    action = (request.POST.get('action') or 'pass').strip()
    items = ensure_deal_design_sections(deal)
    gate = design_gate(items)

    if action == 'reopen':
        if deal.design_passed_at is not None:
            deal.design_passed_at = None
            deal.save(update_fields=['design_passed_at', 'updated_at'])
            record_domain_event(
                actor=request.user,
                event_type='deal.design_reopened',
                entity_model='Deal',
                entity_id=deal.id,
                payload={'deal_id': deal.id},
                request=request,
            )
        return _render_design_block(request, deal)

    if not gate['passed']:
        return HttpResponseBadRequest('Gate not passed')

    deal.design_passed_at = timezone.now()
    deal.save(update_fields=['design_passed_at', 'updated_at'])
    record_domain_event(
        actor=request.user,
        event_type='deal.design_passed',
        entity_model='Deal',
        entity_id=deal.id,
        payload={'deal_id': deal.id},
        request=request,
    )
    return _render_design_block(request, deal)
