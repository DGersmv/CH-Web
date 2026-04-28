"""Наполнение санузлов: шаблон из каталога и строки по версии проекта."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.apps import apps

BATHROOM_TEMPLATE_SECTION_CODE = 'bathroom_template_v1'
MAX_BATHROOMS = 20


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def get_template_cost_items():
    """Позиции шаблона санузла (22 материала + 14 работ), порядок как в Excel."""
    Section = apps.get_model('catalog', 'Section')
    CostItem = apps.get_model('catalog', 'CostItem')

    section = Section.objects.filter(code=BATHROOM_TEMPLATE_SECTION_CODE).first()
    if section is None:
        return CostItem.objects.none()
    return CostItem.objects.filter(section=section, is_active=True).order_by('sort_order', 'id')


def get_template_section():
    """Секция каталога, из которой собирается шаблон наполнения санузла."""
    Section = apps.get_model('catalog', 'Section')
    return Section.objects.filter(code=BATHROOM_TEMPLATE_SECTION_CODE).first()


def _unit_price_from_cost_item(cost_item) -> Decimal:
    """Цена за единицу строки шаблона (материал или работа)."""
    if cost_item.kind == 'material':
        return cost_item.price_material
    if cost_item.kind == 'work':
        return cost_item.price_work
    return cost_item.price_material + cost_item.price_work


def _initial_quantity(cost_item) -> Decimal:
    """Как в Excel: флаг 1/0 умножается на цену — для формы храним qty 1 или 0."""
    return Decimal('1') if cost_item.default_included else Decimal('0')


def _copy_template_lines_to_bathroom(bathroom):
    DealBathroomLine = apps.get_model('deals', 'DealBathroomLine')
    CostItemOption = apps.get_model('catalog', 'CostItemOption')
    template_items = list(get_template_cost_items())
    for ci in template_items:
        selected_option = None
        unit_price = _unit_price_from_cost_item(ci)
        if ci.kind == 'material':
            selected_option = (
                CostItemOption.objects.filter(cost_item_id=ci.pk, is_active=True)
                .exclude(code='customer_material')
                .order_by('sort_order', 'id')
                .first()
            )
            if selected_option is not None:
                unit_price = selected_option.price
                # Options added in deals.0012 had price=0 until catalog.0008; fall back to каталог.
                if unit_price == Decimal('0') and getattr(selected_option, 'code', '') != 'customer_material':
                    unit_price = _unit_price_from_cost_item(ci)
        DealBathroomLine.objects.create(
            bathroom=bathroom,
            cost_item_id=ci.pk,
            name_snapshot=ci.name_ru,
            kind=ci.kind,
            is_included=ci.default_included,
            quantity=_initial_quantity(ci),
            unit_price=unit_price,
            sort_order=ci.sort_order,
            selected_option=selected_option,
        )


def ensure_bathroom_lines_if_empty(bathroom):
    """Если вкладка без строк (миграция / сбой) — заполнить из шаблона."""
    if bathroom.lines.exists():
        return
    _copy_template_lines_to_bathroom(bathroom)


def ensure_bathrooms(version, count: int) -> None:
    """
    Число вкладок санузлов = count (ограничено MAX_BATHROOMS).
    Новые вкладки получают копию строк шаблона; лишние удаляются (высокие index).
    """
    DealBathroom = apps.get_model('deals', 'DealBathroom')

    count = max(0, min(int(count), MAX_BATHROOMS))
    deal_id = version.deal_id

    DealBathroom.objects.filter(project_version=version, index__gt=count).delete()

    for idx in range(1, count + 1):
        bathroom, _created = DealBathroom.objects.get_or_create(
            project_version=version,
            index=idx,
            defaults={'deal_id': deal_id, 'label': ''},
        )
        if bathroom.deal_id != deal_id:
            bathroom.deal_id = deal_id
            bathroom.save(update_fields=['deal_id'])
        ensure_bathroom_lines_if_empty(bathroom)


def bathrooms_totals(version):
    """
    Суммы материалов и работ по всем санузлам версии (учитываются только включённые строки).

    Для каждой строки: если is_included, к сумме добавляется quantity * unit_price.
    """
    DealBathroomLine = apps.get_model('deals', 'DealBathroomLine')

    material_total = Decimal('0')
    work_total = Decimal('0')

    qs = DealBathroomLine.objects.filter(bathroom__project_version=version).values(
        'kind', 'is_included', 'quantity', 'unit_price'
    )
    for row in qs:
        if not row['is_included']:
            continue
        q = Decimal(str(row['quantity']))
        p = Decimal(str(row['unit_price']))
        chunk = _money(q * p)
        kind = row['kind']
        if kind == 'material':
            material_total += chunk
        elif kind == 'work':
            work_total += chunk
        else:
            material_total += _money(chunk / Decimal('2'))
            work_total += _money(chunk / Decimal('2'))

    return _money(material_total), _money(work_total)


def has_bathroom_data(version) -> bool:
    DealBathroom = apps.get_model('deals', 'DealBathroom')
    return DealBathroom.objects.filter(project_version=version).exists()


def bathrooms_count_from_config(frozen_data) -> int:
    """D37 из сохранённого конфигуратора (ограничено MAX_BATHROOMS)."""
    cfg = (frozen_data or {}).get('config_inputs') or {}
    raw = cfg.get('bathrooms_count', 0)
    try:
        n = int(Decimal(str(raw)))
    except (InvalidOperation, ValueError, TypeError):
        return 0
    return max(0, min(n, MAX_BATHROOMS))


def bathrooms_button_enabled(frozen_data) -> bool:
    return bathrooms_count_from_config(frozen_data) >= 1


def bathroom_totals(bathroom):
    """Суммы материалов/работ/итого по одной вкладке санузла."""
    material_total = Decimal('0')
    work_total = Decimal('0')
    for line in bathroom.lines.all().order_by('sort_order', 'id'):
        if not line.is_included:
            continue
        chunk = _money(Decimal(str(line.quantity)) * Decimal(str(line.unit_price)))
        if line.kind == 'material':
            material_total += chunk
        elif line.kind == 'work':
            work_total += chunk
        else:
            material_total += _money(chunk / Decimal('2'))
            work_total += _money(chunk / Decimal('2'))
    subtotal = _money(material_total + work_total)
    return _money(material_total), _money(work_total), subtotal
