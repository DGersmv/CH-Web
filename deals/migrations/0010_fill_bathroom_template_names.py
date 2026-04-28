from decimal import Decimal

from django.db import migrations


MATERIAL_ROWS = [
    ("bath_tpl_mat_01", "Линейный трап", "pcs", Decimal("11000.00"), True),
    ("bath_tpl_mat_02", "Раздвижная перегородка 1200х2000", "pcs", Decimal("60000.00"), True),
    ("bath_tpl_mat_03", "Стационарная стеклянная перегородка 900*2000", "pcs", Decimal("50000.00"), False),
    ("bath_tpl_mat_04", "Душевая стойка c смесителем Am/Pm Sunny F0785C900", "pcs", Decimal("29000.00"), True),
    ("bath_tpl_mat_05", "Гигиенический душ Grohe BauFlow 23632000 с лейкой", "pcs", Decimal("15000.00"), False),
    ("bath_tpl_mat_06", "Ванна", "pcs", Decimal("70000.00"), False),
    ("bath_tpl_mat_07", "Смеситель для раковины Am.Pm Gem", "pcs", Decimal("12000.00"), True),
    ("bath_tpl_mat_08", "Раковина AM.PM. Func", "pcs", Decimal("10000.00"), True),
    ("bath_tpl_mat_09", "Столешница Массив Альфа 1000*470", "pcs", Decimal("7000.00"), True),
    ("bath_tpl_mat_10", "Кронштейн подвесной", "pcs", Decimal("4500.00"), True),
    ("bath_tpl_mat_11", "Сифон для раковины без выпуска", "pcs", Decimal("1500.00"), True),
    ("bath_tpl_mat_12", "Выпуск", "pcs", Decimal("850.00"), True),
    ("bath_tpl_mat_13", "Труба гофрированная 32*900", "pcs", Decimal("650.00"), True),
    ("bath_tpl_mat_14", "Унитаз напольный", "pcs", Decimal("10000.00"), False),
    ("bath_tpl_mat_15", "Бойлер 100л", "pcs", Decimal("20000.00"), True),
    ("bath_tpl_mat_16", "Бойлер 50л", "pcs", Decimal("17000.00"), False),
    ("bath_tpl_mat_17", "Электрический полотенцесушитель Point", "pcs", Decimal("11000.00"), True),
    (
        "bath_tpl_mat_18",
        "Комплект инсталляция с унитазом AM.PM Crave FlashClean с клавишей Pro L, хром, безободковый, микролифт",
        "pcs",
        Decimal("30000.00"),
        True,
    ),
    ("bath_tpl_mat_19", "Греющий кабель", "pcs", Decimal("2500.00"), True),
    ("bath_tpl_mat_20", "Комплект фановых труб и фитингов для подключения канализации под домом", "complex", Decimal("5000.00"), True),
    ("bath_tpl_mat_21", "Незамерзающий уличный кран Unipump", "pcs", Decimal("5000.00"), False),
    ("bath_tpl_mat_22", "Комплект материала для отделки скрытой ниши под коллектор и бойлер", "complex", Decimal("5000.00"), False),
]

WORK_ROWS = [
    ("bath_tpl_work_01", "Бойлер", Decimal("7000.00"), True),
    ("bath_tpl_work_02", "Коллекторный шкаф", Decimal("7000.00"), True),
    ("bath_tpl_work_03", "Подготовка под СМ в с/у", Decimal("7000.00"), True),
    ("bath_tpl_work_04", "Душевая зона в с/у", Decimal("13000.00"), True),
    ("bath_tpl_work_05", "Раковина на столешнице в с/у", Decimal("7000.00"), True),
    ("bath_tpl_work_06", "Инсталляция с унитазом в с/у", Decimal("10000.00"), True),
    ("bath_tpl_work_07", "Подготовка под раковину на кухне", Decimal("7000.00"), True),
    ("bath_tpl_work_08", "Подготовка под ПММ на кухне", Decimal("7000.00"), True),
    ("bath_tpl_work_09", "Соединение фановых труб под домом + ввод воды", Decimal("10000.00"), True),
    ("bath_tpl_work_10", "Монтаж незамерзающего уличного крана", Decimal("7000.00"), False),
    ("bath_tpl_work_11", "Монтаж гигиенического душа", Decimal("7000.00"), False),
    ("bath_tpl_work_12", "Монтаж скрытой ниши под коммуникации", Decimal("7000.00"), False),
    ("bath_tpl_work_13", "Монтаж стеклянной перегородки", Decimal("7000.00"), False),
    ("bath_tpl_work_14", "Монтаж ванны", Decimal("10000.00"), True),
]


def fill_template_names(apps, schema_editor):
    CostItem = apps.get_model("catalog", "CostItem")
    DealBathroomLine = apps.get_model("deals", "DealBathroomLine")

    for sort_order, (code, name_ru, unit, price_material, included) in enumerate(MATERIAL_ROWS, start=1):
        item = CostItem.objects.filter(code=code).first()
        if item is None:
            continue
        item.name_ru = name_ru
        item.unit = unit
        item.price_material = price_material
        item.price_work = Decimal("0.00")
        item.default_included = included
        item.kind = "material"
        item.sort_order = sort_order
        item.is_active = True
        item.save(
            update_fields=[
                "name_ru",
                "unit",
                "price_material",
                "price_work",
                "default_included",
                "kind",
                "sort_order",
                "is_active",
            ]
        )
        DealBathroomLine.objects.filter(cost_item_id=item.id).update(
            name_snapshot=name_ru,
            kind="material",
            unit_price=price_material,
        )

    for idx, (code, name_ru, price_work, included) in enumerate(WORK_ROWS, start=1):
        item = CostItem.objects.filter(code=code).first()
        if item is None:
            continue
        item.name_ru = name_ru
        item.unit = "pcs"
        item.price_material = Decimal("0.00")
        item.price_work = price_work
        item.default_included = included
        item.kind = "work"
        item.sort_order = 100 + idx
        item.is_active = True
        item.save(
            update_fields=[
                "name_ru",
                "unit",
                "price_material",
                "price_work",
                "default_included",
                "kind",
                "sort_order",
                "is_active",
            ]
        )
        DealBathroomLine.objects.filter(cost_item_id=item.id).update(
            name_snapshot=name_ru,
            kind="work",
            unit_price=price_work,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("deals", "0009_dealbathroom_dealbathroomline"),
        ("catalog", "0003_seed_bathroom_template"),
    ]

    operations = [
        migrations.RunPython(fill_template_names, migrations.RunPython.noop),
    ]

