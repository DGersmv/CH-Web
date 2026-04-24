from pathlib import Path

from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Deal, ProjectFile, ProjectVersion, normalize_project_code
from .services.storage_paths import ensure_deal_dirs, get_files_root, get_version_root


class PluginProjectVersionCreateApi(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        payload = request.data

        error = self._validate_payload(payload)
        if error:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)

        normalized_code = normalize_project_code(payload['project_code'])
        deal = Deal.objects.filter(project_code_normalized=normalized_code).first()
        created_deal = False
        if deal is None:
            deal = Deal.objects.create(
                project_code=payload['project_code'].strip(),
                module_count=payload['module_count'],
                status=Deal.Status.ORPHAN,
            )
            created_deal = True
            ensure_deal_dirs(deal)
        elif deal.module_count != payload['module_count']:
            deal.module_count = payload['module_count']
            deal.save(update_fields=['module_count', 'updated_at'])

        ensure_deal_dirs(deal)
        version = deal.create_new_version(source=ProjectVersion.Source.ARCHICAD, created_by=request.user)
        version.frozen_data = {
            'contract_version': 'v0-draft',
            'project_code': payload['project_code'].strip(),
            'module_count': payload['module_count'],
            'source': payload['source'],
            'objects': payload['objects'],
        }
        if payload.get('plan_pdf_filename'):
            raw_filename = payload['plan_pdf_filename'].strip().replace('\\', '/').split('/')[-1]
            plan_relative = get_version_root(version).joinpath('plan', raw_filename).relative_to(get_files_root())
            version.plan_pdf_path = str(plan_relative).replace('\\', '/')
            ProjectFile.objects.create(
                deal=deal,
                project_version=version,
                source=ProjectFile.Source.DESIGNER,
                category=ProjectFile.Category.PDF,
                relative_path=version.plan_pdf_path,
                original_name=raw_filename,
                size_bytes=0,
                ext=Path(raw_filename).suffix.lower().lstrip('.'),
                uploaded_by=request.user,
            )
        version.save(update_fields=['frozen_data', 'plan_pdf_path'])

        return Response(
            {
                'deal_id': deal.id,
                'project_code': deal.project_code,
                'project_version_id': version.id,
                'version_number': version.version_number,
                'created_deal': created_deal,
            },
            status=status.HTTP_201_CREATED,
        )

    def _validate_payload(self, payload):
        if not isinstance(payload, dict):
            return 'Payload must be a JSON object.'

        project_code = payload.get('project_code')
        if not isinstance(project_code, str) or not project_code.strip():
            return 'project_code is required and must be a non-empty string.'

        module_count = payload.get('module_count')
        if not isinstance(module_count, int) or not 1 <= module_count <= 15:
            return 'module_count is required and must be integer in range 1..15.'

        source = payload.get('source')
        if source != 'archicad':
            return 'source must be archicad.'

        objects = payload.get('objects')
        if not isinstance(objects, list) or not objects:
            return 'objects is required and must be a non-empty array.'

        guids = set()
        for obj in objects:
            if not isinstance(obj, dict):
                return 'each object must be an object.'
            guid = obj.get('guid')
            obj_type = obj.get('type')
            params = obj.get('params')
            if not isinstance(guid, str) or not guid.strip():
                return 'objects[].guid is required and must be a non-empty string.'
            if guid in guids:
                return 'objects[].guid must be unique inside payload.'
            if not isinstance(obj_type, str) or not obj_type.strip():
                return 'objects[].type is required and must be a non-empty string.'
            if not isinstance(params, dict):
                return 'objects[].params is required and must be an object.'
            guids.add(guid)

        filename = payload.get('plan_pdf_filename')
        if filename is not None and not isinstance(filename, str):
            return 'plan_pdf_filename must be a string when provided.'

        return None
