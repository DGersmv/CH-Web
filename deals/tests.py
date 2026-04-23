from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

import json
from pathlib import Path

from deals.services.calculation_engine import CALC_SCHEMA_VERSION, build_formula_reconciliation_report, calculate_config

from .models import Deal, ProjectVersion


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
        self.assertEqual(str(totals['material_total']), '6698912.00')
        self.assertEqual(str(totals['work_total']), '1813760.00')
        self.assertEqual(str(totals['subtotal']), '8512672.00')
        self.assertEqual(str(totals['with_margin']), '11066473.60')

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
        self.assertEqual(str(totals['work_total']), '1738660.00')
        self.assertEqual(str(totals['subtotal']), '6202180.00')
        self.assertEqual(str(totals['with_margin']), '7752725.00')

    def test_formula_reconciliation_by_cell_id(self):
        payload = json.loads(Path('/app/docs/excel_extract.json').read_text(encoding='utf-8'))
        report = build_formula_reconciliation_report(payload)
        self.assertTrue(report['ok'], report['rows'])
