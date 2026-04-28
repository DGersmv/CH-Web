from django.db import migrations


OPTION_SPECS = {
    'bath_tpl_mat_01': [('base', 'Базовый трап 800 мм', True), ('premium', 'Премиум трап из нерж. стали', False)],
    'bath_tpl_mat_02': [('base', 'Базовая раздвижная перегородка 1200х2000', True), ('black', 'Перегородка black profile 1200х2000', False)],
    'bath_tpl_mat_03': [('base', 'Базовая стационарная стеклянная перегородка 900*2000', True)],
    'bath_tpl_mat_04': [('ampm_sunny', 'Am/Pm Sunny F0785C900', True), ('grohe', 'Grohe Tempesta / аналог', False)],
    'bath_tpl_mat_05': [('grohe_bauflow', 'Grohe BauFlow 23632000', True), ('ampm_like', 'Am.Pm Like / аналог', False)],
    'bath_tpl_mat_06': [('bath_170', 'Ванна 1700 мм базовая', True), ('bath_acryl', 'Акриловая ванна комфорт', False)],
    'bath_tpl_mat_07': [('ampm_gem', 'Am.Pm Gem', True), ('grohe_start', 'Grohe Start / аналог', False)],
    'bath_tpl_mat_08': [('ampm_func', 'AM.PM Func', True), ('cersanit', 'Cersanit / аналог', False)],
    'bath_tpl_mat_09': [('alpha', 'Столешница Массив Альфа 1000*470', True)],
    'bath_tpl_mat_10': [('bracket_base', 'Кронштейн подвесной базовый', True)],
    'bath_tpl_mat_11': [('siphon_base', 'Сифон для раковины базовый', True)],
    'bath_tpl_mat_12': [('issue_base', 'Выпуск базовый', True)],
    'bath_tpl_mat_13': [('pipe_base', 'Труба гофрированная 32*900', True)],
    'bath_tpl_mat_14': [('floor_wc', 'Унитаз напольный базовый', True)],
    'bath_tpl_mat_15': [('boiler_100', 'Бойлер 100л', True), ('electrolux_100', 'Electrolux 100л / аналог', False)],
    'bath_tpl_mat_16': [('boiler_50', 'Бойлер 50л', True), ('ariston_50', 'Ariston 50л / аналог', False)],
    'bath_tpl_mat_17': [('point', 'Point', True), ('terminus', 'Terminus / аналог', False)],
    'bath_tpl_mat_18': [('ampm_crave', 'AM.PM Crave FlashClean', True), ('grohe_rapid', 'Grohe Rapid SL + чаша', False)],
    'bath_tpl_mat_19': [('cable_base', 'Греющий кабель базовый', True)],
    'bath_tpl_mat_20': [('pipe_kit', 'Комплект фановых труб и фитингов', True)],
    'bath_tpl_mat_21': [('unipump', 'Unipump', True), ('other_frost', 'Незамерзающий кран аналог', False)],
    'bath_tpl_mat_22': [('niche_kit', 'Комплект материала для скрытой ниши', True)],
}


def seed_options(apps, schema_editor):
    CostItem = apps.get_model('catalog', 'CostItem')
    CostItemOption = apps.get_model('catalog', 'CostItemOption')
    DealBathroomLine = apps.get_model('deals', 'DealBathroomLine')

    for code, options in OPTION_SPECS.items():
        item = CostItem.objects.filter(code=code).first()
        if item is None:
            continue
        default_option = None
        for idx, (opt_code, opt_name, is_default) in enumerate(options, start=1):
            option, _ = CostItemOption.objects.update_or_create(
                cost_item=item,
                code=opt_code,
                defaults={
                    'name_ru': opt_name,
                    'description': '',
                    'is_default': is_default,
                    'is_active': True,
                    'sort_order': idx,
                },
            )
            if is_default:
                default_option = option
        if default_option is not None:
            DealBathroomLine.objects.filter(cost_item=item, selected_option__isnull=True).update(selected_option=default_option)


class Migration(migrations.Migration):
    dependencies = [
        ('deals', '0011_dealbathroomline_selected_option'),
    ]

    operations = [
        migrations.RunPython(seed_options, migrations.RunPython.noop),
    ]
