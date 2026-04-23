from decimal import Decimal

from catalog.models import CostItem


def _to_decimal(value):
    if value in (None, ''):
        return Decimal('0')
    return Decimal(str(value))


def _cost_item_map():
    return {item.code: item for item in CostItem.objects.filter(is_active=True)}


def calculate_config(inputs, margin_percent):
    cost_items = _cost_item_map()
    rows = []

    building_area = _to_decimal(inputs.get('building_area'))
    windows_count = _to_decimal(inputs.get('windows_count'))
    sauna_cost = _to_decimal(inputs.get('sauna_cost'))
    floor_key = inputs.get('floor_insulation')
    roof_type = inputs.get('roof_type')

    floor_code = f'floor_insulation_{floor_key}'
    floor_item = cost_items.get(floor_code)
    rows.append(
        _row_from_cost_item(
            label=f'Пол: утепление {floor_key}мм',
            quantity=building_area,
            item=floor_item,
            unit='sqm',
        )
    )

    roof_code = 'roof_metal' if roof_type == 'gable' else 'roof_insulation'
    roof_item = cost_items.get(roof_code)
    rows.append(
        _row_from_cost_item(
            label='Кровля',
            quantity=building_area,
            item=roof_item,
            unit='sqm',
        )
    )

    window_item = cost_items.get('window_double_glazed')
    rows.append(
        _row_from_cost_item(
            label='Окна',
            quantity=windows_count,
            item=window_item,
            unit='pcs',
        )
    )

    rows.append(
        {
            'label': 'Сауна',
            'quantity': Decimal('1') if sauna_cost > 0 else Decimal('0'),
            'unit': 'rubles',
            'price_material': sauna_cost,
            'price_work': Decimal('0'),
            'material_total': sauna_cost,
            'work_total': Decimal('0'),
            'line_total': sauna_cost,
        }
    )

    material_total = sum((row['material_total'] for row in rows), Decimal('0'))
    work_total = sum((row['work_total'] for row in rows), Decimal('0'))
    subtotal = material_total + work_total
    with_margin = subtotal * (Decimal('1') + (Decimal(str(margin_percent)) / Decimal('100')))

    return {
        'rows': rows,
        'totals': {
            'material_total': material_total,
            'work_total': work_total,
            'subtotal': subtotal,
            'with_margin': with_margin,
            'margin_percent': Decimal(str(margin_percent)),
        },
    }


def _row_from_cost_item(label, quantity, item, unit):
    qty = _to_decimal(quantity)
    material_price = _to_decimal(item.price_material) if item else Decimal('0')
    work_price = _to_decimal(item.price_work) if item else Decimal('0')
    material_total = qty * material_price
    work_total = qty * work_price
    return {
        'label': label,
        'quantity': qty,
        'unit': unit,
        'price_material': material_price,
        'price_work': work_price,
        'material_total': material_total,
        'work_total': work_total,
        'line_total': material_total + work_total,
    }
