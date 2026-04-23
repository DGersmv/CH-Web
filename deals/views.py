from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic.edit import FormView
from django.utils import timezone
from decimal import Decimal

from clients.models import Client

from .forms import DealConfiguratorForm, DealCreateForm
from .models import ChangeLog, Deal
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
        return redirect('deal_detail', pk=deal.pk)


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
