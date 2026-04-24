import io
import mimetypes
import shutil
import zipfile
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic.edit import FormView
from django.utils import timezone

from clients.models import Client

from .forms import DashboardLeadForm, DealConfiguratorForm, DealCreateForm, DealFileUploadForm
from .models import ChangeLog, Deal, ProjectFile, build_project_code_from_parts, normalize_project_code
from .services.storage_paths import ensure_deal_dirs, get_deal_root, get_files_root
from .services.calculation_engine import CALC_SCHEMA_VERSION, calculate_config


@login_required
@require_POST
def update_deal_status(request, deal_id):
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


class DealCreateView(LoginRequiredMixin, FormView):
    template_name = 'deal_form.html'
    form_class = DealCreateForm

    def form_valid(self, form):
        deal = form.save(commit=False)
        new_client_name = form.cleaned_data.get('new_client_name', '').strip()
        if new_client_name and not deal.client:
            client, _ = Client.objects.get_or_create(full_name=new_client_name, defaults={'created_by': self.request.user})
            deal.client = client
        deal.save()
        ensure_deal_dirs(deal)
        return redirect('deal_detail', pk=deal.pk)


@login_required
@require_POST
def create_dashboard_lead(request):
    form = DashboardLeadForm(request.POST)
    if not form.is_valid():
        return render(request, 'includes/dashboard_lead_modal_body.html', {'lead_form': form}, status=400)

    full_name = ' '.join(
        part.strip()
        for part in [
            form.cleaned_data['last_name'],
            form.cleaned_data['first_name'],
            form.cleaned_data.get('middle_name', ''),
        ]
        if part and part.strip()
    )
    site_name = form.cleaned_data['location'].strip()
    module_count = form.cleaned_data['module_count']
    lead_project_code = build_project_code_from_parts(module_count, form.cleaned_data['last_name'].strip(), site_name)
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
    location_text = f'Участок: {site_name}'
    if address_text:
        location_text = f'{location_text}. Адрес: {address_text}'
    client = Client.objects.create(
        full_name=full_name,
        phone=form.cleaned_data['phone'],
        email=form.cleaned_data.get('email', ''),
        location=location_text,
        notes=(form.cleaned_data.get('comment') or '').strip(),
        created_by=request.user,
    )
    deal = Deal.objects.create(
        project_code=lead_project_code,
        code_client_name=form.cleaned_data['last_name'].strip(),
        code_site_name=site_name,
        module_count=module_count,
        client=client,
        status=Deal.Status.NEW,
        mortgage_required=form.cleaned_data['mortgage_required'],
        target_deal_date=form.cleaned_data['target_deal_date'],
    )
    ensure_deal_dirs(deal)
    response = HttpResponse('')
    response['HX-Redirect'] = redirect('deal_detail', pk=deal.pk).url
    return response


@login_required
@require_POST
def update_deal_module_count(request, deal_id):
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
    return Path('system')


def _files_summary(deal, source: str):
    qs = deal.project_files.filter(source=source, is_archived=False).order_by('-updated_at')
    latest = qs.first()
    return {
        'items': qs,
        'latest': latest,
        'count': qs.count(),
    }


def _files_context(deal, **extra):
    context = {
        'deal': deal,
        'client_files': _files_summary(deal, ProjectFile.Source.CLIENT),
        'designer_files': _files_summary(deal, ProjectFile.Source.DESIGNER),
        'client_upload_form': DealFileUploadForm(initial={'source': ProjectFile.Source.CLIENT}),
        'designer_upload_form': DealFileUploadForm(initial={'source': ProjectFile.Source.DESIGNER}),
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


@login_required
@require_POST
def upload_project_file(request, deal_id):
    deal = get_object_or_404(Deal, pk=deal_id)
    form = DealFileUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(
            request,
            'includes/deal_files_block.html',
            _files_context(deal, files_error='Не удалось загрузить файл.'),
            status=400,
        )

    source = form.cleaned_data['source']
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

    ProjectFile.objects.create(
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
    return render(
        request,
        'includes/deal_files_block.html',
        _files_context(deal, files_notice='Файл загружен.'),
    )


@login_required
@xframe_options_sameorigin
def open_project_file(request, file_id):
    file_obj = get_object_or_404(ProjectFile, pk=file_id, is_archived=False)
    absolute_path = file_obj.absolute_path
    if not absolute_path.exists() or not absolute_path.is_file():
        raise Http404('File not found')
    return FileResponse(absolute_path.open('rb'), as_attachment=False, filename=file_obj.original_name)


@login_required
@require_POST
def archive_project_file(request, file_id):
    file_obj = get_object_or_404(ProjectFile, pk=file_id, is_archived=False)
    deal = file_obj.deal
    source = file_obj.source
    _archive_file(file_obj, request.user)

    return render(
        request,
        'includes/deal_files_block.html',
        _files_context(deal, files_notice='Файл перемещён в архив.', focus_source=source),
    )


@login_required
@require_POST
def bulk_project_file_action(request, deal_id, source):
    deal = get_object_or_404(Deal, pk=deal_id)
    if source not in {ProjectFile.Source.CLIENT, ProjectFile.Source.DESIGNER}:
        return HttpResponseBadRequest('Invalid source')
    selected_ids = [int(v) for v in request.POST.getlist('selected_ids') if v.isdigit()]
    if not selected_ids:
        return render(
            request,
            'includes/deal_files_block.html',
            _files_context(deal, files_error='Выберите хотя бы один файл.'),
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
            _archive_file(file_obj, request.user)
            count += 1
        return render(
            request,
            'includes/deal_files_block.html',
            _files_context(deal, files_notice=f'В архив перемещено: {count}.'),
        )

    if action == 'preview':
        first = files_qs.first()
        if not first:
            return render(
                request,
                'includes/deal_files_block.html',
                _files_context(deal, files_error='Файлы не найдены.'),
                status=404,
            )
        return open_project_file(request, first.id)

    if action == 'download':
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for file_obj in files_qs:
                path = file_obj.absolute_path
                if path.exists() and path.is_file():
                    zf.write(path, arcname=file_obj.original_name)
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


@login_required
@require_POST
def update_deal_cost_summary(request, deal_id):
    deal = get_object_or_404(Deal, pk=deal_id)
    draft = _get_or_create_draft_version(deal, request.user)
    frozen = draft.frozen_data or {}
    calculation = frozen.get('calculation') or {}
    totals = dict(calculation.get('totals') or {})

    materials_total = _parse_decimal(request.POST.get('materials_total'))
    work_total = _parse_decimal(request.POST.get('work_total'))
    subtotal = _parse_decimal(request.POST.get('subtotal'))
    with_margin = _parse_decimal(request.POST.get('with_margin'))
    if None in {materials_total, work_total, subtotal, with_margin}:
        return HttpResponseBadRequest('Invalid totals payload')

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

    response = HttpResponse('')
    response['HX-Redirect'] = redirect('deal_detail', pk=deal.pk).url
    return response


@login_required
@require_POST
def recalc_configurator(request, deal_id):
    deal = get_object_or_404(Deal, pk=deal_id)
    form = DealConfiguratorForm(request.POST)
    calc_result = None
    if form.is_valid():
        calc_result = calculate_config(form.cleaned_data, margin_percent=deal.margin_percent)
    return render(
        request,
        'includes/configurator_block.html',
        {
            'deal': deal,
            'config_form': form,
            'calc_result': calc_result,
            'draft_version': _get_or_create_draft_version(deal, request.user),
            'save_success': False,
        },
        status=200 if form.is_valid() else 400,
    )


@login_required
@require_POST
def save_configurator_draft(request, deal_id):
    deal = get_object_or_404(Deal, pk=deal_id)
    form = DealConfiguratorForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            'includes/configurator_block.html',
            {
                'deal': deal,
                'config_form': form,
                'calc_result': None,
                'draft_version': _get_or_create_draft_version(deal, request.user),
                'save_success': False,
            },
            status=400,
        )

    calc_result = calculate_config(form.cleaned_data, margin_percent=deal.margin_percent)
    draft = _get_or_create_draft_version(deal, request.user)
    old_inputs = (draft.frozen_data or {}).get('config_inputs', {})
    new_inputs = form.cleaned_data
    changed_keys = [key for key in new_inputs.keys() if str(old_inputs.get(key, '')) != str(new_inputs.get(key, ''))]

    draft.frozen_data = {
        'calc_schema_version': CALC_SCHEMA_VERSION,
        'config_inputs': _json_ready(new_inputs),
        'calculation': _json_ready(calc_result),
        'saved_at': timezone.now().isoformat(),
    }
    draft.save(update_fields=['frozen_data'])

    for key in changed_keys:
        ChangeLog.objects.create(
            project_version=draft,
            changed_by=request.user,
            field_path=f'config.{key}',
            old_value={'value': _json_ready(old_inputs.get(key))},
            new_value={'value': _json_ready(new_inputs.get(key))},
        )

    return render(
        request,
        'includes/configurator_block.html',
        {
            'deal': deal,
            'config_form': form,
            'calc_result': calc_result,
            'draft_version': draft,
            'save_success': True,
        },
    )


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
