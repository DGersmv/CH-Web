from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

import json
import tempfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

from django.test import override_settings
from django.urls import reverse

from catalog.models import CostItem, CostItemOption

from deals.forms import BathroomLineFormSet
from deals.services.bathrooms import bathrooms_totals, ensure_bathrooms
from deals.services.additional_options import ensure_additional_option_lines, additional_options_totals
from deals.services.calculation_engine import (
    CALC_SCHEMA_VERSION,
    _bathroom_sheet_totals,
    build_formula_reconciliation_report,
    calculate_config,
)
from deals.services.storage_paths import ensure_deal_dirs, ensure_version_dirs, get_deal_root

from .forms import DashboardLeadForm
from .models import (
    Deal,
    DealAdditionalOptionLine,
    DealBathroom,
    DealBathroomLine,
    ProjectFile,
    ProjectVersion,
    build_project_code_from_parts,
)


class PluginProjectVersionCreateApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='plugin_user', password='pass1234', role='designer')
        self.token = Token.objects.create(user=self.user)
        self.url = '/api/plugin/project-versions/'
        self.payload = {
            'project_code': '3МД Иванов Пулково',
            'module_count': 3,
            'source': 'archicad',
            'plan_pdf_filename': 'plan_ivanov_v3.pdf',
            'objects': [
                {
                    'guid': 'AC-OBJ-001',
                    'type': 'wall',
                    'params': {'length_mm': 4200, 'height_mm': 2800, 'thickness_mm': 200},
                }
            ],
        }

    def test_requires_token(self):
        response = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 401)

    def test_creates_orphan_deal_and_archicad_version(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        response = self.client.post(self.url, self.payload, format='json')

        self.assertEqual(response.status_code, 201)
        deal = Deal.objects.get(project_code_normalized='3мд иванов пулково')
        version = deal.versions.get(version_number=1)
        self.assertEqual(deal.status, Deal.Status.ORPHAN)
        self.assertEqual(version.source, ProjectVersion.Source.ARCHICAD)
        self.assertEqual(version.frozen_data['objects'][0]['guid'], 'AC-OBJ-001')
        self.assertIn('/versions/v1/plan/', version.plan_pdf_path)
        self.assertEqual(ProjectFile.objects.filter(deal=deal, source=ProjectFile.Source.DESIGNER).count(), 1)
        self.assertTrue(response.data['created_deal'])

    def test_creates_new_version_for_existing_deal(self):
        deal = Deal.objects.create(project_code='3МД Иванов Пулково', module_count=3, status=Deal.Status.NEW)
        deal.create_new_version(source=ProjectVersion.Source.MANUAL, created_by=self.user)

        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        response = self.client.post(self.url, self.payload, format='json')

        self.assertEqual(response.status_code, 201)
        deal.refresh_from_db()
        self.assertEqual(deal.versions.count(), 2)
        self.assertEqual(deal.versions.order_by('-version_number').first().source, ProjectVersion.Source.ARCHICAD)
        self.assertFalse(response.data['created_deal'])

    def test_rejects_duplicate_guid(self):
        bad_payload = {
            **self.payload,
            'objects': [
                {'guid': 'dup', 'type': 'wall', 'params': {}},
                {'guid': 'dup', 'type': 'window', 'params': {}},
            ],
        }
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        response = self.client.post(self.url, bad_payload, format='json')
        self.assertEqual(response.status_code, 400)


class BuildProjectCodeTests(TestCase):
    def test_dash_separated_format(self):
        self.assertEqual(build_project_code_from_parts(2, 'Иванов', 'Пулково'), '2МД-Иванов-Пулково')
        self.assertEqual(build_project_code_from_parts(3, '  ООО  Тест  ', ' Уч. 1 '), '3МД-ООО Тест-Уч. 1')


class CreateDashboardLeadProjectCodeTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='mgr_lead', password='pass1234', role='manager')

    def test_lead_project_code_uses_first_name_not_last_name(self):
        self.client.force_login(self.user)
        url = reverse('dashboard_lead_create')
        response = self.client.post(
            url,
            {
                'module_count': 5,
                'last_name': 'Уточнить',
                'first_name': 'Апатиты',
                'middle_name': '',
                'phone': '+79000000000',
                'email': 'apatity@example.com',
                'portal_password': 'client123',
                'location': 'Участок1',
                'region_or_city': '',
                'street': '',
                'house_number': '',
                'comment': '',
                'target_deal_date': '2026-05-04',
            },
        )
        self.assertEqual(response.status_code, 200)
        deal = Deal.objects.get(project_code='5МД-Апатиты-Участок1')
        self.assertEqual(deal.code_client_name, 'Апатиты')
        self.assertEqual(deal.client.last_name, 'Уточнить')
        self.assertEqual(deal.client.first_name, 'Апатиты')


class DashboardLeadFormTests(TestCase):
    def test_phone_defaults_to_plus7_when_empty(self):
        form = DashboardLeadForm(
            data={
                'module_count': 0,
                'last_name': 'Иванов',
                'first_name': 'Иван',
                'middle_name': 'Иванович',
                'phone': '',
                'email': 'ivanov@example.com',
                'portal_password': 'client123',
                'location': 'Пулково',
                'region_or_city': 'Ленинградская область',
                'street': 'Центральная',
                'house_number': '12',
                'comment': 'Предпочитает связь в мессенджере вечером',
                'target_deal_date': '2026-04-24',
            }
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['phone'], '+7')

    def test_phone_must_start_with_plus7(self):
        form = DashboardLeadForm(
            data={
                'module_count': 0,
                'last_name': 'Иванов',
                'first_name': 'Иван',
                'middle_name': '',
                'phone': '89001234567',
                'email': 'ivanov@example.com',
                'portal_password': 'client123',
                'location': 'Пулково',
                'region_or_city': 'Ленинградская область',
                'street': 'Центральная',
                'house_number': '12',
                'comment': '',
                'target_deal_date': '2026-04-24',
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)

    def test_address_fields_can_be_empty(self):
        form = DashboardLeadForm(
            data={
                'module_count': 0,
                'last_name': 'Иванов',
                'first_name': 'Иван',
                'middle_name': '',
                'phone': '+79001234567',
                'email': 'ivanov@example.com',
                'portal_password': 'client123',
                'location': 'Пулково',
                'region_or_city': '',
                'street': '',
                'house_number': '',
                'comment': 'Тест',
                'target_deal_date': '2026-04-24',
            }
        )
        self.assertTrue(form.is_valid())


class StoragePathsTests(TestCase):
    @override_settings(CRM_FILES_ROOT=tempfile.gettempdir())
    def test_ensure_deal_dirs_creates_source_folders(self):
        deal = Deal.objects.create(project_code='0МД-Тест-Участок', module_count=0, status=Deal.Status.NEW)
        ensure_deal_dirs(deal)
        deal_root = get_deal_root(deal)
        self.assertTrue((deal_root / 'incoming/client/photos').exists())
        self.assertTrue((deal_root / 'incoming/designer/plans_pdf').exists())
        self.assertTrue((deal_root / 'archive').exists())

    @override_settings(CRM_FILES_ROOT=tempfile.gettempdir())
    def test_ensure_version_dirs_creates_plan_and_quote(self):
        deal = Deal.objects.create(project_code='1МД-Тест-Участок', module_count=1, status=Deal.Status.NEW)
        version = deal.create_new_version(source=ProjectVersion.Source.MANUAL)
        ensure_version_dirs(version)
        version_root = get_deal_root(deal) / 'versions' / f'v{version.version_number}'
        self.assertTrue((version_root / 'plan').exists())
        self.assertTrue((version_root / 'quote').exists())


class DealCostSummaryUpdateTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='manager1', password='pass1234', role='manager')
        self.client.force_login(self.user)
        self.deal = Deal.objects.create(
            project_code='3МД-Иванов-Пулково',
            module_count=3,
            code_client_name='Иванов',
            code_site_name='Пулково',
            status=Deal.Status.NEW,
        )
        self.version = self.deal.create_new_version(source=ProjectVersion.Source.MANUAL, created_by=self.user)
        self.version.frozen_data = {
            'config_inputs': {'building_area': '120'},
            'calculation': {
                'totals': {
                    'material_total': 100,
                    'work_total': 50,
                    'subtotal': 150,
                    'with_margin': 195,
                    'margin_percent': 30,
                }
            },
        }
        self.version.save(update_fields=['frozen_data'])

    def test_updates_cost_summary_totals(self):
        url = reverse('deal_cost_summary_update', kwargs={'deal_id': self.deal.id})
        response = self.client.post(
            url,
            {
                'materials_total': '5391912.00',
                'work_total': '1748760.00',
                'subtotal': '7140672.00',
                'with_margin': '9282873.60',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.version.refresh_from_db()
        totals = self.version.frozen_data['calculation']['totals']
        self.assertEqual(float(totals['material_total']), 5391912.00)
        self.assertEqual(float(totals['with_margin']), 9282873.60)

    def test_rejects_negative_totals(self):
        url = reverse('deal_cost_summary_update', kwargs={'deal_id': self.deal.id})
        response = self.client.post(
            url,
            {
                'materials_total': '-1',
                'work_total': '1',
                'subtotal': '1',
                'with_margin': '1',
            },
        )
        self.assertEqual(response.status_code, 400)


class ExcelRegressionCalculationTests(TestCase):
    def test_regression_case_base_configuration(self):
        inputs = {
            'building_area': '120',
            'living_area': '90',
            'ceiling_height': '2.7',
            'floor_150_qty': '0',
            'floor_200_qty': '120',
            'floor_250_qty': '0',
            'floor_laminate_qty': '90',
            'floor_tile_qty': '0',
            'facade_planken_lm': '0',
            'facade_combined_lm': '48',
            'partition_double_lm': '24',
            'partition_single_lm': '16',
            'finish_quarter_lm': '0',
            'finish_ldsp_lm': '48',
            'finish_gkl_lm': '0',
            'finish_mdf_lm': '0',
            'finish_plywood_lm': '0',
            'bathroom_tile_lm': '0',
            'roof_gable_qty': '120',
            'roof_flat_qty': '0',
            'interior_doors_count': 5,
            'windows_count': 8,
            'windows_total_cost': '120000',
            'panoramic_sections_count': 1,
            'panoramic_sections_total_cost': '55000',
            'sauna_cost': '280000',
            'sauna_installation_cost': '45000',
            'bathrooms_count': 1,
        }
        result = calculate_config(inputs, margin_percent='30')
        totals = result['totals']
        self.assertEqual(result['schema_version'], CALC_SCHEMA_VERSION)
        self.assertEqual(str(totals['material_total']), '5858912.00')
        self.assertEqual(str(totals['work_total']), '1771760.00')
        self.assertEqual(str(totals['subtotal']), '7630672.00')
        self.assertEqual(str(totals['with_margin']), '9919873.60')

    def test_regression_case_flat_roof_and_granite(self):
        inputs = {
            'building_area': '80',
            'living_area': '65',
            'ceiling_height': '2.5',
            'floor_150_qty': '80',
            'floor_200_qty': '0',
            'floor_250_qty': '0',
            'floor_laminate_qty': '0',
            'floor_tile_qty': '65',
            'facade_planken_lm': '0',
            'facade_combined_lm': '40',
            'partition_double_lm': '12',
            'partition_single_lm': '20',
            'finish_quarter_lm': '0',
            'finish_ldsp_lm': '0',
            'finish_gkl_lm': '40',
            'finish_mdf_lm': '0',
            'finish_plywood_lm': '0',
            'bathroom_tile_lm': '0',
            'roof_gable_qty': '0',
            'roof_flat_qty': '80',
            'interior_doors_count': 4,
            'windows_count': 6,
            'windows_total_cost': '0',
            'panoramic_sections_count': 0,
            'panoramic_sections_total_cost': '0',
            'sauna_cost': '0',
            'sauna_installation_cost': '0',
            'bathrooms_count': 1,
        }
        result = calculate_config(inputs, margin_percent='25')
        totals = result['totals']
        self.assertEqual(str(totals['material_total']), '4463520.00')
        self.assertEqual(str(totals['work_total']), '1714660.00')
        self.assertEqual(str(totals['subtotal']), '6178180.00')
        self.assertEqual(str(totals['with_margin']), '7722725.00')

    def test_formula_reconciliation_by_cell_id(self):
        payload = json.loads(Path('/app/docs/excel_extract.json').read_text(encoding='utf-8'))
        report = build_formula_reconciliation_report(payload)
        self.assertTrue(report['ok'], report['rows'])


class BathroomTemplateTests(TestCase):
    """Шаблон санузла из каталога и строки DealBathroom."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='manager_bt', password='pass1234', role='manager')
        self.deal = Deal.objects.create(
            project_code='1МД-ТестБаня-Уч',
            module_count=1,
            code_client_name='ТестБаня',
            code_site_name='Уч',
            status=Deal.Status.NEW,
        )
        self.version = self.deal.create_new_version(source=ProjectVersion.Source.MANUAL, created_by=self.user)

    def test_bathrooms_totals_zero_without_tabs(self):
        m, w = bathrooms_totals(self.version)
        self.assertEqual(m, Decimal('0.00'))
        self.assertEqual(w, Decimal('0.00'))

    def test_ensure_one_bathroom_matches_legacy_sheet_totals(self):
        ensure_bathrooms(self.version, 1)
        n_lines = DealBathroomLine.objects.filter(bathroom__project_version=self.version).count()
        self.assertGreater(n_lines, 0, 'санузел должен получить строки шаблона')
        kinds = Counter(
            DealBathroomLine.objects.filter(bathroom__project_version=self.version).values_list('kind', flat=True)
        )
        self.assertEqual(kinds.get('material', 0), 22, kinds)
        self.assertEqual(kinds.get('work', 0), 14, kinds)
        bm, bw = bathrooms_totals(self.version)
        lm, lw = _bathroom_sheet_totals()
        self.assertEqual(bm, lm)
        self.assertEqual(bw, lw)

    def test_calculate_config_with_version_matches_without_when_template_default(self):
        """При данных вкладок по умолчанию итоги сметы совпадают с расчётом без version."""
        ensure_bathrooms(self.version, 1)
        inputs = {
            'building_area': '120',
            'living_area': '90',
            'ceiling_height': '2.7',
            'floor_150_qty': '0',
            'floor_200_qty': '120',
            'floor_250_qty': '0',
            'floor_laminate_qty': '90',
            'floor_tile_qty': '0',
            'facade_planken_lm': '0',
            'facade_combined_lm': '48',
            'partition_double_lm': '24',
            'partition_single_lm': '16',
            'finish_quarter_lm': '0',
            'finish_ldsp_lm': '48',
            'finish_gkl_lm': '0',
            'finish_mdf_lm': '0',
            'finish_plywood_lm': '0',
            'bathroom_tile_lm': '0',
            'roof_gable_qty': '120',
            'roof_flat_qty': '0',
            'interior_doors_count': 5,
            'windows_count': 8,
            'windows_total_cost': '120000',
            'panoramic_sections_count': 1,
            'panoramic_sections_total_cost': '55000',
            'sauna_cost': '280000',
            'sauna_installation_cost': '45000',
            'bathrooms_count': 1,
        }
        r1 = calculate_config(inputs, margin_percent='30')
        r2 = calculate_config(inputs, margin_percent='30', version=self.version)
        self.assertEqual(
            r1['totals']['material_total'] - r2['totals']['material_total'],
            Decimal('60000.00'),
        )
        self.assertEqual(r1['totals']['work_total'], r2['totals']['work_total'])

    def test_calculate_config_with_version_uses_exact_bathroom_totals(self):
        ensure_bathrooms(self.version, 1)
        inputs = {
            'building_area': '0',
            'living_area': '0',
            'ceiling_height': '2.7',
            'floor_150_qty': '0',
            'floor_200_qty': '0',
            'floor_250_qty': '0',
            'floor_laminate_qty': '0',
            'floor_tile_qty': '0',
            'facade_planken_lm': '0',
            'facade_combined_lm': '0',
            'partition_double_lm': '0',
            'partition_single_lm': '0',
            'finish_quarter_lm': '0',
            'finish_ldsp_lm': '0',
            'finish_gkl_lm': '0',
            'finish_mdf_lm': '0',
            'finish_plywood_lm': '0',
            'bathroom_tile_lm': '0',
            'roof_gable_qty': '0',
            'roof_flat_qty': '0',
            'interior_doors_count': '0',
            'windows_count': '0',
            'windows_total_cost': '0',
            'panoramic_sections_count': '0',
            'panoramic_sections_total_cost': '0',
            'sauna_cost': '0',
            'sauna_installation_cost': '0',
            'bathrooms_count': 1,
        }
        result = calculate_config(inputs, margin_percent='30', version=self.version)
        bm, bw = bathrooms_totals(self.version)
        self.assertEqual(result['totals']['material_total'], bm)
        self.assertEqual(result['totals']['work_total'], bw)

    def test_customer_material_option_present_for_each_material(self):
        materials = CostItem.objects.filter(section__code='bathroom_template_v1', kind='material')
        self.assertGreater(materials.count(), 0)
        for ci in materials:
            opt = ci.options.filter(code='customer_material').first()
            self.assertIsNotNone(opt, ci.code)
            self.assertEqual(opt.price, Decimal('0'))

    def test_two_bathrooms_have_same_default_lines_and_selected_option(self):
        ensure_bathrooms(self.version, 2)
        brs = list(DealBathroom.objects.filter(project_version=self.version).order_by('index'))
        self.assertEqual(len(brs), 2)
        lines1 = list(brs[0].lines.order_by('sort_order', 'id'))
        lines2 = list(brs[1].lines.order_by('sort_order', 'id'))
        self.assertEqual(len(lines1), len(lines2))
        for a, b in zip(lines1, lines2):
            self.assertEqual(a.name_snapshot, b.name_snapshot)
            self.assertEqual(a.kind, b.kind)
            self.assertEqual(a.selected_option_id, b.selected_option_id)

    def test_material_lines_pick_first_non_customer_option(self):
        ensure_bathrooms(self.version, 1)
        br = DealBathroom.objects.filter(project_version=self.version).first()
        for line in br.lines.filter(kind='material'):
            ci = line.cost_item
            expected = (
                ci.options.filter(is_active=True).exclude(code='customer_material').order_by('sort_order', 'id').first()
            )
            self.assertIsNotNone(expected)
            self.assertEqual(line.selected_option_id, expected.id)


class BathroomOptionPricingTests(TestCase):
    """Цена строки от модели + создание модели через API."""

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='mgr_opt', password='pass1234', role='manager')
        self.client.force_login(self.user)
        self.deal = Deal.objects.create(
            project_code='2МД-Опт-Уч',
            module_count=2,
            code_client_name='Опт',
            code_site_name='Уч',
            status=Deal.Status.NEW,
        )
        self.version = self.deal.create_new_version(source=ProjectVersion.Source.MANUAL, created_by=self.user)
        self.version.frozen_data = {
            'config_inputs': {'bathrooms_count': 1},
            'calculation': {},
        }
        self.version.save(update_fields=['frozen_data'])

    def test_create_cost_item_option_endpoint(self):
        ci = CostItem.objects.filter(section__code='bathroom_template_v1', kind='material').first()
        if ci is None:
            self.skipTest('no bathroom template items')
        url = reverse('cost_item_option_create', kwargs={'cost_item_id': ci.pk})
        resp = self.client.post(
            url,
            {
                'name_ru': 'Тестовая модель API',
                'manufacturer': 'ACME',
                'article': 'ART-1',
                'country': 'Россия',
                'unit': '',
                'price': '999.50',
                'description': '',
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        opt_id = data['option']['id']
        self.assertTrue(CostItemOption.objects.filter(pk=opt_id, cost_item=ci).exists())

    def test_save_tab_applies_option_price(self):
        ensure_bathrooms(self.version, 1)
        br = DealBathroom.objects.filter(project_version=self.version).first()
        self.assertIsNotNone(br)
        line = DealBathroomLine.objects.filter(bathroom=br, kind='material').first()
        self.assertIsNotNone(line)
        self.assertIsNotNone(line.cost_item)
        alt = line.cost_item.options.exclude(pk=line.selected_option_id).first()
        if alt is None:
            alt = CostItemOption.objects.create(
                cost_item=line.cost_item,
                code='opt-test-alt',
                name_ru='Альтернатива',
                price=Decimal('7777.01'),
                unit=line.cost_item.unit,
            )
        else:
            alt.price = Decimal('7777.01')
            alt.save(update_fields=['price'])

        fs = BathroomLineFormSet(instance=br)
        prefix = fs.prefix
        rows = list(br.lines.order_by('id'))
        data = {
            f'{prefix}-TOTAL_FORMS': len(rows),
            f'{prefix}-INITIAL_FORMS': len(rows),
            f'{prefix}-MIN_NUM_FORMS': 0,
            f'{prefix}-MAX_NUM_FORMS': 1000,
        }
        for i, ln in enumerate(rows):
            data[f'{prefix}-{i}-id'] = ln.id
            data[f'{prefix}-{i}-bathroom'] = br.id
            if ln.is_included:
                data[f'{prefix}-{i}-is_included'] = 'on'
            opt_id = alt.id if ln.id == line.id else ln.selected_option_id
            data[f'{prefix}-{i}-selected_option'] = str(opt_id) if opt_id else ''
            data[f'{prefix}-{i}-quantity'] = str(ln.quantity)
            data[f'{prefix}-{i}-unit_price'] = str(ln.unit_price)

        url = reverse('deal_bathroom_tab_save', kwargs={'deal_id': self.deal.id, 'bathroom_id': br.id})
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        line.refresh_from_db()
        self.assertEqual(line.selected_option_id, alt.id)
        self.assertEqual(line.unit_price, Decimal('7777.01'))

    def test_manual_unit_price_kept_when_option_unchanged(self):
        ensure_bathrooms(self.version, 1)
        br = DealBathroom.objects.filter(project_version=self.version).first()
        line = DealBathroomLine.objects.filter(bathroom=br, kind='material').first()
        original_opt = line.selected_option_id
        custom_price = Decimal('4321.00')

        fs = BathroomLineFormSet(instance=br)
        prefix = fs.prefix
        rows = list(br.lines.order_by('id'))
        data = {
            f'{prefix}-TOTAL_FORMS': len(rows),
            f'{prefix}-INITIAL_FORMS': len(rows),
            f'{prefix}-MIN_NUM_FORMS': 0,
            f'{prefix}-MAX_NUM_FORMS': 1000,
        }
        for i, ln in enumerate(rows):
            data[f'{prefix}-{i}-id'] = ln.id
            data[f'{prefix}-{i}-bathroom'] = br.id
            if ln.is_included:
                data[f'{prefix}-{i}-is_included'] = 'on'
            data[f'{prefix}-{i}-selected_option'] = str(ln.selected_option_id) if ln.selected_option_id else ''
            up = custom_price if ln.id == line.id else ln.unit_price
            data[f'{prefix}-{i}-quantity'] = str(ln.quantity)
            data[f'{prefix}-{i}-unit_price'] = str(up)

        url = reverse('deal_bathroom_tab_save', kwargs={'deal_id': self.deal.id, 'bathroom_id': br.id})
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)
        line.refresh_from_db()
        self.assertEqual(line.unit_price, custom_price)
        self.assertEqual(line.selected_option_id, original_opt)


class AdditionalOptionsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='manager_add', password='pass1234', role='manager')
        self.client.force_login(self.user)
        self.deal = Deal.objects.create(
            project_code='1МД-Допы-Тест',
            module_count=1,
            code_client_name='Допы',
            code_site_name='Тест',
            status=Deal.Status.NEW,
        )
        self.version = self.deal.create_new_version(source=ProjectVersion.Source.MANUAL, created_by=self.user)

    def test_additional_options_page_builds_lines(self):
        url = reverse('deal_additional_options_page', kwargs={'deal_id': self.deal.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(DealAdditionalOptionLine.objects.filter(project_version=self.version).count(), 12)

    def test_additional_options_affect_totals_with_version(self):
        ensure_additional_option_lines(self.version)
        line = DealAdditionalOptionLine.objects.filter(project_version=self.version).first()
        line.is_included = True
        line.quantity = Decimal('2')
        line.unit_price = Decimal('5000')
        line.save(update_fields=['is_included', 'quantity', 'unit_price'])

        inputs = {
            'building_area': '0',
            'living_area': '0',
            'ceiling_height': '2.7',
            'floor_150_qty': '0',
            'floor_200_qty': '0',
            'floor_250_qty': '0',
            'floor_laminate_qty': '0',
            'floor_tile_qty': '0',
            'facade_planken_lm': '0',
            'facade_combined_lm': '0',
            'partition_double_lm': '0',
            'partition_single_lm': '0',
            'finish_quarter_lm': '0',
            'finish_ldsp_lm': '0',
            'finish_gkl_lm': '0',
            'finish_mdf_lm': '0',
            'finish_plywood_lm': '0',
            'bathroom_tile_lm': '0',
            'roof_gable_qty': '0',
            'roof_flat_qty': '0',
            'interior_doors_count': '0',
            'windows_count': '0',
            'windows_total_cost': '0',
            'panoramic_sections_count': '0',
            'panoramic_sections_total_cost': '0',
            'sauna_cost': '0',
            'sauna_installation_cost': '0',
            'bathrooms_count': 0,
        }
        result = calculate_config(inputs, margin_percent='30', version=self.version)
        m_add, w_add = additional_options_totals(self.version)
        self.assertEqual(result['totals']['material_total'], Decimal('0.00'))
        self.assertEqual(result['totals']['work_total'], Decimal('0.00'))
        self.assertEqual(result['additional_options']['material_total'], m_add)
        self.assertEqual(result['additional_options']['work_total'], w_add)

    def test_can_create_custom_additional_option(self):
        url = reverse('deal_additional_options_create', kwargs={'deal_id': self.deal.id})
        resp = self.client.post(
            url,
            {
                'name': 'Мой кастом',
                'unit': 'pcs',
                'quantity': '3',
                'unit_price': '1234',
                'is_included': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        created = DealAdditionalOptionLine.objects.filter(project_version=self.version, name_snapshot='Мой кастом').first()
        self.assertIsNotNone(created)
        self.assertEqual(created.unit_snapshot, 'pcs')
