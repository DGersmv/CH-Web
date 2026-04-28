from django.db import migrations


MATERIAL_NAME_UPDATES = {
    "bath_tpl_mat_01": "Линейный трап",
    "bath_tpl_mat_02": "Раздвижная перегородка 1200х2000",
    "bath_tpl_mat_03": "Стационарная стеклянная перегородка 900*2000",
    "bath_tpl_mat_04": "Душевая стойка со смесителем",
    "bath_tpl_mat_05": "Гигиенический душ с лейкой",
    "bath_tpl_mat_06": "Ванна",
    "bath_tpl_mat_07": "Смеситель для раковины",
    "bath_tpl_mat_08": "Раковина",
    "bath_tpl_mat_09": "Столешница Массив Альфа 1000*470",
    "bath_tpl_mat_10": "Кронштейн подвесной",
    "bath_tpl_mat_11": "Сифон для раковины без выпуска",
    "bath_tpl_mat_12": "Выпуск",
    "bath_tpl_mat_13": "Труба гофрированная 32*900",
    "bath_tpl_mat_14": "Унитаз напольный",
    "bath_tpl_mat_15": "Бойлер 100л",
    "bath_tpl_mat_16": "Бойлер 50л",
    "bath_tpl_mat_17": "Электрический полотенцесушитель",
    "bath_tpl_mat_18": "Комплект инсталляции с унитазом",
    "bath_tpl_mat_19": "Греющий кабель",
    "bath_tpl_mat_20": "Комплект фановых труб и фитингов для подключения канализации под домом",
    "bath_tpl_mat_21": "Незамерзающий уличный кран",
    "bath_tpl_mat_22": "Комплект материала для отделки скрытой ниши под коллектор и бойлер",
}


def forwards(apps, schema_editor):
    CostItem = apps.get_model("catalog", "CostItem")
    DealBathroomLine = apps.get_model("deals", "DealBathroomLine")

    for code, new_name in MATERIAL_NAME_UPDATES.items():
        item = CostItem.objects.filter(code=code).first()
        if item is None:
            continue
        item.name_ru = new_name
        item.save(update_fields=["name_ru"])
        DealBathroomLine.objects.filter(cost_item_id=item.id).update(name_snapshot=new_name)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0006_backfill_option_prices"),
        ("deals", "0012_seed_bathroom_options"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

