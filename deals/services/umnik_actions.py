"""Действия умника внутри CRM: сделки, конфигуратор, суммы."""
from __future__ import annotations

import shutil
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import can_delete_deals, can_edit_deals, umnik_capabilities
from deals.forms import DealConfiguratorForm
from deals.models import ChangeLog, Deal, ProjectVersion, normalize_project_code
from deals.services.bathrooms import bathrooms_count_from_config, ensure_bathrooms
from deals.services.calculation_engine import CALC_SCHEMA_VERSION, calculate_config
from deals.services.storage_paths import get_deal_root
from system_settings.events import record_domain_event


CONFIG_FIELDS = tuple(DealConfiguratorForm.base_fields.keys())
DEAL_STATUSES = {value for value, _label in Deal.Status.choices}


def _json_ready(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    return value


def _as_decimal(raw):
    try:
        value = Decimal(str(raw).replace(',', '.').replace(' ', ''))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if value < 0:
        return None
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _draft(deal, user):
    draft = deal.versions.filter(status=ProjectVersion.Status.DRAFT).order_by('-version_number').first()
    if draft is None:
        draft = deal.create_new_version(source='manual', created_by=user)
    return draft


def _config_initial(deal, user):
    from deals.views import _draft_config_initial

    return _draft_config_initial(deal, user)


def whoami(user) -> dict:
    return {'ok': True, **umnik_capabilities(user)}


def _forbid_edit(user):
    if can_edit_deals(user):
        return None
    return {
        'ok': False,
        'error': 'forbidden',
        'detail': 'У этой роли нет права менять сделки. Можно только смотреть.',
    }


def _forbid_delete(user):
    if can_delete_deals(user):
        return None
    return {
        'ok': False,
        'error': 'forbidden',
        'detail': 'Удалять сделки может только admin.',
    }


def _checklist_summary(context, list_key, gate_key, accepted=None):
    """Сводка по чек-листу (согласования / проектирование) для умника."""
    gate = context[gate_key]
    items = context[list_key]
    return {
        'gate': {
            'required_total': gate['required_total'],
            'required_satisfied': gate['required_satisfied'],
            'passed': gate['passed'],
        },
        'accepted_version': getattr(accepted, 'version_number', None),
        'blocking': [i.slug for i in gate['blocking']],
        'items': [
            {
                'slug': i.slug,
                'title': i.title,
                'hint': i.hint,
                'status': i.status,
                'status_label': i.get_status_display(),
                'is_required': i.is_required,
                'is_satisfied': i.is_satisfied,
                'is_custom': i.is_custom,
                'comment': i.comment,
                'notes': i.notes,
                'project_version': getattr(i.project_version, 'version_number', None),
                'decided_by': getattr(i.decided_by, 'username', '') or '',
                'decided_at': i.decided_at.isoformat() if i.decided_at else None,
            }
            for i in items
        ],
    }


def deal_summaries(deal) -> dict:
    """Все сводки по сделке: версии, согласования, проектирование, санузлы."""
    from deals.services.approvals import build_approvals_context
    from deals.services.design import build_design_context
    from deals.services.bathrooms import bathrooms_count_from_config

    approvals_ctx = build_approvals_context(deal)
    design_ctx = build_design_context(deal)
    versions = list(deal.versions.select_related('created_by').order_by('-version_number'))
    latest = versions[0] if versions else None
    frozen = (latest.frozen_data or {}) if latest else {}
    return {
        'versions': [
            {
                'number': v.version_number,
                'status': v.status,
                'status_label': v.get_status_display(),
                'source': v.source,
                'created_by': getattr(v.created_by, 'username', '') or '',
                'created_at': v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ],
        'accepted_version': getattr(approvals_ctx['approvals_accepted_version'], 'version_number', None),
        'approvals': _checklist_summary(
            approvals_ctx, 'approvals_list', 'approvals_gate',
            accepted=approvals_ctx['approvals_accepted_version'],
        ),
        'design': _checklist_summary(design_ctx, 'design_sections_list', 'design_gate'),
        'bathrooms_count': bathrooms_count_from_config(frozen),
        'config_filled': bool(frozen.get('config_inputs')),
    }


def serialize_deal(deal, user=None, with_summaries=True) -> dict:
    client = deal.client
    draft = _draft(deal, user) if user is not None else deal.versions.order_by('-version_number').first()
    frozen = (draft.frozen_data or {}) if draft else {}
    calc = frozen.get('calculation') or {}
    totals = calc.get('totals') or {}
    payload = {
        'id': deal.id,
        'project_code': deal.project_code,
        'status': deal.status,
        'module_count': deal.module_count,
        'margin_percent': float(deal.margin_percent),
        'code_client_name': deal.code_client_name,
        'code_site_name': deal.code_site_name,
        'manager': getattr(deal.assigned_manager, 'username', '') or '',
        'client': {
            'name': client.full_name if client else '',
            'phone': getattr(client, 'phone', '') or '',
            'email': getattr(client, 'email', '') or '',
        },
        'draft_version': getattr(draft, 'version_number', None),
        'config_inputs': frozen.get('config_inputs') or {},
        'totals': _json_ready(totals),
        'url': reverse('deal_detail', kwargs={'pk': deal.pk}),
    }
    if with_summaries:
        try:
            payload['summaries'] = _json_ready(deal_summaries(deal))
        except Exception as exc:  # сводки не должны ронять карточку
            payload['summaries'] = {'error': str(exc)}
    return payload


def search_deals(query: str, limit: int = 20) -> list[dict]:
    qs = Deal.objects.select_related('client', 'assigned_manager').order_by('-updated_at')
    q = (query or '').strip()
    if q:
        qs = qs.filter(
            Q(project_code__icontains=q)
            | Q(code_client_name__icontains=q)
            | Q(code_site_name__icontains=q)
            | Q(client__last_name__icontains=q)
            | Q(client__first_name__icontains=q)
            | Q(client__company_name__icontains=q)
        )
    try:
        cap = int(limit or 20)
    except (TypeError, ValueError):
        cap = 20
    return [
        {
            'id': deal.id,
            'project_code': deal.project_code,
            'status': deal.status,
            'module_count': deal.module_count,
            'manager': getattr(deal.assigned_manager, 'username', '') or '',
        }
        for deal in qs[: max(1, min(cap, 50))]
    ]


def find_deal(deal_id=None, project_code: str = '') -> Deal | None:
    if deal_id not in (None, ''):
        try:
            return Deal.objects.select_related('client', 'assigned_manager').filter(pk=int(deal_id)).first()
        except (TypeError, ValueError):
            return None
    code = (project_code or '').strip()
    if not code:
        return None
    return (
        Deal.objects.select_related('client', 'assigned_manager')
        .filter(project_code_normalized=normalize_project_code(code))
        .first()
    )


def update_deal(deal: Deal, user, fields: dict) -> dict:
    blocked = _forbid_edit(user)
    if blocked:
        return blocked
    changed = []
    data = fields or {}

    if 'status' in data:
        status = str(data['status']).strip()
        if status not in DEAL_STATUSES:
            return {'ok': False, 'error': f'unknown status: {status}', 'allowed': sorted(DEAL_STATUSES)}
        if deal.status != status:
            ChangeLog.objects.create(
                project_version=_draft(deal, user),
                changed_by=user,
                field_path='status',
                old_value={'value': deal.status},
                new_value={'value': status},
            )
            deal.status = status
            changed.append('status')

    if 'margin_percent' in data:
        margin = _as_decimal(data['margin_percent'])
        if margin is None:
            return {'ok': False, 'error': 'invalid margin_percent'}
        if Decimal(str(deal.margin_percent)) != margin:
            ChangeLog.objects.create(
                project_version=_draft(deal, user),
                changed_by=user,
                field_path='margin_percent',
                old_value={'value': float(deal.margin_percent)},
                new_value={'value': float(margin)},
            )
            deal.margin_percent = margin
            changed.append('margin_percent')

    if 'module_count' in data:
        try:
            modules = int(data['module_count'])
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'invalid module_count'}
        if modules < 0 or modules > 15:
            return {'ok': False, 'error': 'module_count must be 0..15'}
        if deal.module_count != modules:
            ChangeLog.objects.create(
                project_version=_draft(deal, user),
                changed_by=user,
                field_path='module_count',
                old_value={'value': deal.module_count},
                new_value={'value': modules},
            )
            deal.module_count = modules
            changed.append('module_count')

    if 'project_code' in data:
        code = str(data['project_code']).strip()
        if not code:
            return {'ok': False, 'error': 'empty project_code'}
        if deal.project_code != code:
            deal.project_code = code
            changed.append('project_code')

    if 'code_client_name' in data:
        deal.code_client_name = str(data['code_client_name'] or '').strip()
        changed.append('code_client_name')

    if 'code_site_name' in data:
        deal.code_site_name = str(data['code_site_name'] or '').strip()
        changed.append('code_site_name')

    if 'assigned_manager' in data:
        username = str(data['assigned_manager'] or '').strip()
        manager = None
        if username:
            manager = get_user_model().objects.filter(username=username, is_active=True).first()
            if manager is None:
                return {'ok': False, 'error': f'unknown manager: {username}'}
        deal.assigned_manager = manager
        changed.append('assigned_manager')

    if changed:
        deal.save()
    return {'ok': True, 'changed': changed, 'deal': serialize_deal(deal, user)}


def update_config(deal: Deal, user, fields: dict) -> dict:
    blocked = _forbid_edit(user)
    if blocked:
        return blocked
    unknown = [key for key in (fields or {}) if key not in CONFIG_FIELDS]
    if unknown:
        return {'ok': False, 'error': 'unknown config fields', 'unknown': unknown, 'allowed': list(CONFIG_FIELDS)}
    draft, initial = _config_initial(deal, user)
    merged = dict(initial)
    for key, value in (fields or {}).items():
        merged[key] = value
    form = DealConfiguratorForm({key: '' if value is None else str(value) for key, value in merged.items()})
    if not form.is_valid():
        return {'ok': False, 'error': 'invalid config', 'details': form.errors.get_json_data()}

    new_inputs = form.cleaned_data
    old_inputs = (draft.frozen_data or {}).get('config_inputs', {})
    changed_keys = [key for key in new_inputs if str(old_inputs.get(key, '')) != str(new_inputs.get(key, ''))]
    draft.frozen_data = {
        'calc_schema_version': CALC_SCHEMA_VERSION,
        'config_inputs': _json_ready(new_inputs),
        'saved_at': timezone.now().isoformat(),
    }
    draft.save(update_fields=['frozen_data'])
    ensure_bathrooms(draft, bathrooms_count_from_config(draft.frozen_data))
    calc_result = calculate_config(new_inputs, margin_percent=deal.margin_percent, version=draft)
    frozen = draft.frozen_data or {}
    frozen['calculation'] = _json_ready(calc_result)
    frozen['saved_at'] = timezone.now().isoformat()
    draft.frozen_data = frozen
    draft.save(update_fields=['frozen_data'])
    for key in changed_keys:
        ChangeLog.objects.create(
            project_version=draft,
            changed_by=user,
            field_path=f'config.{key}',
            old_value={'value': _json_ready(old_inputs.get(key))},
            new_value={'value': _json_ready(new_inputs.get(key))},
        )
    return {
        'ok': True,
        'changed': True,
        'changed_keys': changed_keys,
        'totals': _json_ready((calc_result or {}).get('totals') or {}),
        'deal': serialize_deal(deal, user),
    }


def update_cost(deal: Deal, user, fields: dict) -> dict:
    blocked = _forbid_edit(user)
    if blocked:
        return blocked
    materials = _as_decimal((fields or {}).get('materials_total'))
    work = _as_decimal((fields or {}).get('work_total'))
    if materials is None or work is None:
        return {'ok': False, 'error': 'need materials_total and work_total'}
    draft = _draft(deal, user)
    frozen = draft.frozen_data or {}
    calculation = frozen.get('calculation') or {}
    totals = dict(calculation.get('totals') or {})
    subtotal = (materials + work).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
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
            'material_total': materials,
            'work_total': work,
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
        changed_by=user,
        field_path='cost_summary_manual_edit',
        old_value=_json_ready(old_totals),
        new_value=_json_ready(
            {
                'material_total': materials,
                'work_total': work,
                'subtotal': subtotal,
                'with_margin': with_margin,
            }
        ),
    )
    return {'ok': True, 'changed': True, 'totals': _json_ready(totals), 'deal': serialize_deal(deal, user)}


def delete_deal(deal: Deal, user) -> dict:
    blocked = _forbid_delete(user)
    if blocked:
        return blocked
    deal_id = deal.id
    code = deal.project_code
    folder = None
    try:
        folder = get_deal_root(deal)
    except Exception:
        folder = None
    record_domain_event(
        actor=user,
        event_type='deal.deleted',
        entity_model='Deal',
        entity_id=deal_id,
        payload={'project_code': code},
    )
    deal.delete()
    if folder is not None:
        try:
            if folder.exists() and folder.is_dir():
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass
    return {'ok': True, 'deleted': {'id': deal_id, 'project_code': code}}
