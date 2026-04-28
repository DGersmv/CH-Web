"""Дополнительные опции: шаблон из каталога и строки в версии проекта."""

from decimal import Decimal, ROUND_HALF_UP

from django.apps import apps

ADDITIONAL_OPTIONS_SECTION_CODE = 'additional_options_template_v1'


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def get_additional_template_cost_items():
    Section = apps.get_model('catalog', 'Section')
    CostItem = apps.get_model('catalog', 'CostItem')
    section = Section.objects.filter(code=ADDITIONAL_OPTIONS_SECTION_CODE).first()
    if section is None:
        return CostItem.objects.none()
    return CostItem.objects.filter(section=section, is_active=True).order_by('sort_order', 'id')


def ensure_additional_option_lines(version):
    DealAdditionalOptionLine = apps.get_model('deals', 'DealAdditionalOptionLine')
    if DealAdditionalOptionLine.objects.filter(project_version=version).exists():
        return
    for ci in get_additional_template_cost_items():
        unit_price = ci.price_material if ci.kind != 'work' else ci.price_work
        DealAdditionalOptionLine.objects.create(
            project_version=version,
            cost_item_id=ci.pk,
            name_snapshot=ci.name_ru,
            kind=ci.kind,
            is_included=False,
            quantity=Decimal('0'),
            unit_price=unit_price,
            unit_snapshot=ci.unit,
            sort_order=ci.sort_order,
        )


def additional_options_totals(version):
    DealAdditionalOptionLine = apps.get_model('deals', 'DealAdditionalOptionLine')
    material_total = Decimal('0')
    work_total = Decimal('0')
    qs = DealAdditionalOptionLine.objects.filter(project_version=version).values(
        'kind', 'is_included', 'quantity', 'unit_price'
    )
    for row in qs:
        if not row['is_included']:
            continue
        chunk = _money(Decimal(str(row['quantity'])) * Decimal(str(row['unit_price'])))
        if row['kind'] == 'material':
            material_total += chunk
        elif row['kind'] == 'work':
            work_total += chunk
        else:
            material_total += _money(chunk / Decimal('2'))
            work_total += _money(chunk / Decimal('2'))
    return _money(material_total), _money(work_total)


def additional_options_rows(version):
    DealAdditionalOptionLine = apps.get_model('deals', 'DealAdditionalOptionLine')
    rows = []
    for line in DealAdditionalOptionLine.objects.filter(project_version=version).order_by('sort_order', 'id'):
        if not line.is_included:
            continue
        rows.append(
            {
                'name': line.name_snapshot,
                'unit': line.unit_snapshot or '',
                'quantity': line.quantity,
                'unit_price': line.unit_price,
                'line_total': line.line_total,
            }
        )
    return rows
