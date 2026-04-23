from decimal import Decimal, ROUND_HALF_UP

CALC_SCHEMA_VERSION = 'excel-v1'

ROW_LABELS = {
    'project_design': 'Проект',
    'floor_insulation_150': 'Пол 150мм',
    'floor_insulation_200': 'Пол 200мм',
    'floor_insulation_250': 'Пол 250мм',
    'floor_finish_laminate': 'Чистовой пол - ламинат',
    'floor_finish_granite': 'Чистовой пол - плитка',
    'facade_planken': 'Наружный фасад - планкен сосновый',
    'facade_combined': 'Наружный фасад - комбинированный',
    'outer_wall': 'Стенка наружная',
    'partition_double': 'Перегородка внутр.сдвоенная',
    'partition_single': 'Перегородка внутр. одинарная',
    'finish_quarter_board': 'Интерьерная доска "в четверть"',
    'finish_ldsp': 'Отделка ЛДСП плитами',
    'finish_gkl_paint': 'Отделка ГКЛ в 2 слоя с покраской',
    'finish_mdf': 'Отделка МДФ панелями',
    'finish_plywood_rail': 'Отделка Фанера/рейка',
    'roof_gable': 'Крыша двускатная',
    'roof_flat': 'Крыша плоская(конструктив)',
    'roof_flat_weld': 'Наплавка плоской кровли(кровельщик)',
    'stretch_ceiling': 'Потолок натяжной',
    'finish_bathroom_tile': 'Подготовка стен санузла с плиткой',
    'interior_doors': 'Двери',
    'sauna': 'Сауна',
    'window_finishing': 'Отделка окон',
    'windows_total': 'Окна+монтаж',
    'panoramic_finishing': 'Отделка панорамной стенки',
    'panoramic_sections_total': 'Панорамная стенка+монтаж',
    'store_and_paint': 'Кладовщики+малярка',
    'electrics': 'Электрика',
    'plumbing': 'Сантехника',
    'bathroom_equipment': 'Оборудование санузла',
    'convectors': 'Конвектора+клапан',
    'consumables': 'Расходные материалы',
    'packaging': 'Упаковка +сборка',
    'placeholder_38': 'Строка 38',
    'placeholder_39': 'Строка 39',
    'placeholder_40': 'Строка 40',
    'placeholder_41': 'Строка 41',
    'placeholder_42': 'Строка 42',
    'overhead_costs': 'Накладные расходы',
}

EXCEL_INPUT_MAPPING = {
    'Площадь застройки дома(наружные габариты)': 'building_area',
    'Жилая площадь дома(без учета сауны)': 'living_area',
    'Высота чистового потолка': 'ceiling_height',
    'Погонные метры наружного фасада(доска/брусок, планкен)': 'facade_combined_lm',
    'Погонные метры сдвоенных перегородок(200мм)': 'partition_double_lm',
    'Погонные метры одинарных перегородок(100мм)': 'partition_single_lm',
    'Двери межкомнатные с комплектом доборных элементов': 'interior_doors_count',
    'Окна': 'windows_count',
    'Сауна': 'sauna_cost',
    'Монтаж сауны, печи': 'sauna_installation_cost',
    'Большие панорамные секции (более 5 кв.м)': 'panoramic_sections_count',
    'Стоимость больших панорамных секций': 'panoramic_sections_total_cost',
    'Количество санузлов': 'bathrooms_count',
}


def _to_decimal(value):
    if value in (None, ''):
        return Decimal('0')
    return Decimal(str(value))


def _money(value):
    return _to_decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _safe_mul(a, b):
    return _money(_to_decimal(a) * _to_decimal(b))


def _bathroom_sheet_totals():
    material_specs = [('1', '11000'), ('1', '60000'), ('0', '50000'), ('1', '29000'), ('0', '15000'), ('0', '70000'),
                      ('1', '12000'), ('1', '10000'), ('1', '7000'), ('1', '4500'), ('1', '1500'), ('1', '850'),
                      ('1', '650'), ('0', '10000'), ('1', '20000'), ('0', '17000'), ('1', '11000'), ('1', '30000'),
                      ('1', '2500'), ('1', '5000'), ('0', '5000'), ('0', '5000')]
    work_specs = [('1', '7000'), ('1', '7000'), ('1', '7000'), ('1', '13000'), ('1', '7000'), ('1', '10000'),
                  ('1', '7000'), ('1', '7000'), ('1', '10000'), ('0', '7000'), ('0', '7000'), ('0', '7000'),
                  ('0', '7000'), ('1', '10000')]
    bathroom_material_total = sum((_safe_mul(qty, price) for qty, price in material_specs), Decimal('0'))
    bathroom_work_total = sum((_safe_mul(qty, price) for qty, price in work_specs), Decimal('0'))
    return _money(bathroom_material_total), _money(bathroom_work_total)


def _rule(rule_id, cell_qty, cell_total, unit, quantity, price_material, price_work):
    qty = _to_decimal(quantity)
    pm = _to_decimal(price_material)
    pw = _to_decimal(price_work)
    material_total = _money(qty * pm)
    work_total = _money(qty * pw)
    return {
        'rule_id': rule_id,
        'code': rule_id,
        'excel_cell_qty': cell_qty,
        'excel_cell_total': cell_total,
        'label': ROW_LABELS.get(rule_id, rule_id),
        'quantity': qty,
        'unit': unit,
        'price_material': pm,
        'price_work': pw,
        'material_total': material_total,
        'work_total': work_total,
        'line_total': _money(material_total + work_total),
        'source': 'excel_rule',
    }


def build_formula_reconciliation_report(excel_extract):
    sheet = next((s for s in excel_extract if s.get('sheet') == 'Таблица обзорная'), None)
    if not sheet:
        return {'ok': False, 'errors': ['Sheet not found'], 'rows': []}
    excel_formulas = {f['cell']: f['formula'] for f in sheet.get('formulas', [])}
    checks = {
        'floor_insulation_150': ('C5', "='Таблица для заполнения'!D7"),
        'finish_ldsp': ('C16', "='Таблица для заполнения'!D21*('Таблица для заполнения'!D5+0.05)"),
        'roof_gable': ('C20', "='Таблица для заполнения'!D27*1.15"),
        'plumbing': ('C33', "='Таблица для заполнения'!D37"),
        'bathroom_equipment': ('C34', "='Таблица для заполнения'!D37"),
        'overhead_costs': ('C43', '=C1'),
    }
    rows = []
    for rule_id, (cell, expected) in checks.items():
        actual = excel_formulas.get(cell)
        rows.append({'rule_id': rule_id, 'cell': cell, 'expected': expected, 'actual': actual, 'ok': actual == expected})
    return {'ok': all(r['ok'] for r in rows), 'errors': [], 'rows': rows}


def calculate_config(inputs, margin_percent):
    building_area = _to_decimal(inputs.get('building_area'))
    living_area = _to_decimal(inputs.get('living_area'))
    ceiling_height = _to_decimal(inputs.get('ceiling_height'))
    floor_150_qty = _to_decimal(inputs.get('floor_150_qty'))
    floor_200_qty = _to_decimal(inputs.get('floor_200_qty'))
    floor_250_qty = _to_decimal(inputs.get('floor_250_qty'))
    floor_laminate_qty = _to_decimal(inputs.get('floor_laminate_qty'))
    floor_tile_qty = _to_decimal(inputs.get('floor_tile_qty'))
    facade_planken_lm = _to_decimal(inputs.get('facade_planken_lm'))
    facade_combined_lm = _to_decimal(inputs.get('facade_combined_lm'))
    partition_double_lm = _to_decimal(inputs.get('partition_double_lm'))
    partition_single_lm = _to_decimal(inputs.get('partition_single_lm'))
    finish_quarter_lm = _to_decimal(inputs.get('finish_quarter_lm'))
    finish_ldsp_lm = _to_decimal(inputs.get('finish_ldsp_lm'))
    finish_gkl_lm = _to_decimal(inputs.get('finish_gkl_lm'))
    finish_mdf_lm = _to_decimal(inputs.get('finish_mdf_lm'))
    finish_plywood_lm = _to_decimal(inputs.get('finish_plywood_lm'))
    bathroom_tile_lm = _to_decimal(inputs.get('bathroom_tile_lm'))
    roof_gable_qty = _to_decimal(inputs.get('roof_gable_qty'))
    roof_flat_qty = _to_decimal(inputs.get('roof_flat_qty'))
    interior_doors_count = _to_decimal(inputs.get('interior_doors_count'))
    sauna_cost = _to_decimal(inputs.get('sauna_cost'))
    sauna_installation_cost = _to_decimal(inputs.get('sauna_installation_cost'))
    windows_count = _to_decimal(inputs.get('windows_count'))
    windows_total_cost = _to_decimal(inputs.get('windows_total_cost'))
    panoramic_sections_count = _to_decimal(inputs.get('panoramic_sections_count'))
    panoramic_sections_total_cost = _to_decimal(inputs.get('panoramic_sections_total_cost'))
    bathrooms_count = _to_decimal(inputs.get('bathrooms_count'))

    facade_planken_area = _money(facade_planken_lm * (ceiling_height + Decimal('0.95')))
    facade_combined_area = _money(facade_combined_lm * (ceiling_height + Decimal('0.95')))
    outer_wall_area = _money(facade_combined_lm * (ceiling_height + Decimal('0.15')))
    partition_double_area = _money(partition_double_lm * (ceiling_height + Decimal('0.15')))
    partition_single_area = _money(partition_single_lm * (ceiling_height + Decimal('0.15')))
    quarter_area = _money(finish_quarter_lm * (ceiling_height + Decimal('0.05')))
    ldsp_area = _money(finish_ldsp_lm * (ceiling_height + Decimal('0.05')))
    gkl_area = _money(finish_gkl_lm * (ceiling_height + Decimal('0.05')))
    mdf_area = _money(finish_mdf_lm * (ceiling_height + Decimal('0.05')))
    plywood_area = _money(finish_plywood_lm * (ceiling_height + Decimal('0.05')))
    bathroom_tile_area = _money(bathroom_tile_lm * (ceiling_height + Decimal('0.05')))
    roof_gable_area = _money(roof_gable_qty * Decimal('1.15'))
    roof_flat_area = _money(roof_flat_qty)
    bath2_material_total, bath2_work_total = _bathroom_sheet_totals()

    rows = [
        _rule('project_design', 'C4', 'I4', 'sqm', building_area, '0', '500'),
        _rule('floor_insulation_150', 'C5', 'I5', 'sqm', floor_150_qty, '3360', '950'),
        _rule('floor_insulation_200', 'C6', 'I6', 'sqm', floor_200_qty, '3800', '1200'),
        _rule('floor_insulation_250', 'C7', 'I7', 'sqm', floor_250_qty, '4200', '1050'),
        _rule('floor_finish_laminate', 'C8', 'I8', 'sqm', floor_laminate_qty, '2200', '600'),
        _rule('floor_finish_granite', 'C9', 'I9', 'sqm', floor_tile_qty, '9570', '4000'),
        _rule('facade_planken', 'C10', 'I10', 'sqm', facade_planken_area, '2450', '900'),
        _rule('facade_combined', 'C11', 'I11', 'sqm', facade_combined_area, '2830', '1200'),
        _rule('outer_wall', 'C12', 'I12', 'sqm', outer_wall_area, '2050', '600'),
        _rule('partition_double', 'C13', 'I13', 'sqm', partition_double_area, '2500', '1200'),
        _rule('partition_single', 'C14', 'I14', 'sqm', partition_single_area, '1410', '600'),
        _rule('finish_quarter_board', 'C15', 'I15', 'sqm', quarter_area, '1400', '600'),
        _rule('finish_ldsp', 'C16', 'I16', 'sqm', ldsp_area, '2000', '1500'),
        _rule('finish_gkl_paint', 'C17', 'I17', 'sqm', gkl_area, '2100', '3500'),
        _rule('finish_mdf', 'C18', 'I18', 'sqm', mdf_area, '7000', '1500'),
        _rule('finish_plywood_rail', 'C19', 'I19', 'sqm', plywood_area, '3450', '1200'),
        _rule('roof_gable', 'C20', 'I20', 'sqm', roof_gable_area, '4720', '1500'),
        _rule('roof_flat', 'C21', 'I21', 'sqm', roof_flat_area, '7580', '1600'),
        _rule('roof_flat_weld', 'C22', 'I22', 'sqm', roof_flat_qty, '0', '1000'),
        _rule('stretch_ceiling', 'C23', 'I23', 'sqm', living_area, '1000', '700'),
        _rule('finish_bathroom_tile', 'C24', 'I24', 'sqm', bathroom_tile_area, '6100', '4000'),
        _rule('interior_doors', 'C25', 'I25', 'pcs', interior_doors_count, '28000', '8000'),
        _rule('sauna', 'D26/F26', 'I26', 'rubles', Decimal('1') if sauna_cost > 0 or sauna_installation_cost > 0 else Decimal('0'), sauna_cost, sauna_installation_cost),
        _rule('window_finishing', 'C27', 'I27', 'pcs', windows_count, '6000', '4000'),
        _rule('windows_total', 'C28', 'I28', 'pcs', windows_count, windows_total_cost, '4000'),
        _rule('panoramic_finishing', 'C29', 'I29', 'pcs', panoramic_sections_count, '12000', '10000'),
        _rule('panoramic_sections_total', 'C30', 'I30', 'pcs', panoramic_sections_count, panoramic_sections_total_cost, '10000'),
        _rule('store_and_paint', 'C31', 'I31', 'sqm', building_area, '0', '1700'),
        _rule('electrics', 'C32', 'I32', 'sqm', building_area, '2600', '1800'),
        _rule('plumbing', 'C33', 'I33', 'set', bathrooms_count, '60000', bath2_work_total),
        _rule('bathroom_equipment', 'C34', 'I34', 'set', bathrooms_count, bath2_material_total, '0'),
        _rule('convectors', 'C35', 'I35', 'sqm', building_area, '600', '100'),
        _rule('consumables', 'C36', 'I36', 'sqm', building_area, '1600', '0'),
        _rule('packaging', 'C37', 'I37', 'sqm', building_area, '600', '0'),
        _rule('placeholder_38', 'C38', 'I38', 'none', '0', '0', '0'),
        _rule('placeholder_39', 'C39', 'I39', 'none', '0', '0', '0'),
        _rule('placeholder_40', 'C40', 'I40', 'none', '0', '0', '0'),
        _rule('placeholder_41', 'C41', 'I41', 'none', '0', '0', '0'),
        _rule('placeholder_42', 'C42', 'I42', 'none', '0', '0', '0'),
        _rule('overhead_costs', 'C43', 'I43', 'sqm', building_area, '13500', '0'),
    ]

    material_total = _money(sum((row['material_total'] for row in rows), Decimal('0')))
    work_total = _money(sum((row['work_total'] for row in rows), Decimal('0')))
    subtotal = _money(material_total + work_total)
    with_margin = _money(subtotal * (Decimal('1') + (Decimal(str(margin_percent)) / Decimal('100'))))
    return {
        'schema_version': CALC_SCHEMA_VERSION,
        'excel_input_mapping': EXCEL_INPUT_MAPPING,
        'rows': rows,
        'totals': {
            'material_total': material_total,
            'work_total': work_total,
            'subtotal': subtotal,
            'with_margin': with_margin,
            'margin_percent': Decimal(str(margin_percent)),
        },
    }
