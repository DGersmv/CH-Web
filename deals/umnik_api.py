"""Внутренний API CRM для умника. Тот же Bearer, что UMNIK_TOKEN."""
from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from deals.models import UmnikChatAttachment
from deals.services import umnik_actions


def _token_ok(request) -> bool:
    expected = (getattr(settings, 'UMNIK_TOKEN', '') or '').strip()
    header = request.META.get('HTTP_AUTHORIZATION', '')
    return bool(expected) and header == f'Bearer {expected}'


def _actor(request):
    expected = (getattr(settings, 'UMNIK_TOKEN', '') or '').strip()
    header = request.META.get('HTTP_AUTHORIZATION', '')
    if not expected or header != f'Bearer {expected}':
        return None
    username = (request.META.get('HTTP_X_UMNIK_ACTOR') or 'admin').strip()
    return get_user_model().objects.filter(username=username, is_active=True).first()


def _json_body(request) -> dict:
    raw = request.body.decode('utf-8') if request.body else ''
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _deny():
    return JsonResponse({'ok': False, 'error': 'unauthorized'}, status=401)


@csrf_exempt
@require_http_methods(['GET'])
def umnik_me(request):
    user = _actor(request)
    if user is None:
        return _deny()
    return JsonResponse(umnik_actions.whoami(user))


@csrf_exempt
@require_http_methods(['GET'])
def umnik_chat_attachment_download(request, attachment_id):
    """Отдаёт умнику файл вложения по Bearer-токену (умник на другой машине)."""
    if not _token_ok(request):
        return _deny()
    att = get_object_or_404(UmnikChatAttachment, pk=attachment_id)
    path = att.absolute_path
    if not path.exists() or not path.is_file():
        raise Http404('file not found')
    response = FileResponse(path.open('rb'), as_attachment=True, filename=att.original_name)
    if att.mime_type:
        response['Content-Type'] = att.mime_type
    return response


@csrf_exempt
@require_http_methods(['GET'])
def umnik_deal_list(request):
    user = _actor(request)
    if user is None:
        return _deny()
    items = umnik_actions.search_deals(request.GET.get('q', ''), limit=request.GET.get('limit') or 20)
    return JsonResponse({'ok': True, 'deals': items})


@csrf_exempt
@require_http_methods(['GET', 'PATCH', 'DELETE'])
def umnik_deal_detail(request, deal_id):
    user = _actor(request)
    if user is None:
        return _deny()
    deal = umnik_actions.find_deal(deal_id=deal_id)
    if deal is None:
        return JsonResponse({'ok': False, 'error': 'deal not found'}, status=404)
    if request.method == 'GET':
        return JsonResponse({'ok': True, 'deal': umnik_actions.serialize_deal(deal, user)})
    if request.method == 'DELETE':
        result = umnik_actions.delete_deal(deal, user)
        status = 200 if result.get('ok') else (403 if result.get('error') == 'forbidden' else 400)
        return JsonResponse(result, status=status)
    result = umnik_actions.update_deal(deal, user, _json_body(request))
    status = 200 if result.get('ok') else (403 if result.get('error') == 'forbidden' else 400)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_http_methods(['GET'])
def umnik_deal_lookup(request):
    user = _actor(request)
    if user is None:
        return _deny()
    deal = umnik_actions.find_deal(project_code=request.GET.get('project_code', ''))
    if deal is None:
        return JsonResponse({'ok': False, 'error': 'deal not found'}, status=404)
    return JsonResponse({'ok': True, 'deal': umnik_actions.serialize_deal(deal, user)})


@csrf_exempt
@require_http_methods(['PATCH'])
def umnik_deal_config(request, deal_id):
    user = _actor(request)
    if user is None:
        return _deny()
    deal = umnik_actions.find_deal(deal_id=deal_id)
    if deal is None:
        return JsonResponse({'ok': False, 'error': 'deal not found'}, status=404)
    result = umnik_actions.update_config(deal, user, _json_body(request))
    status = 200 if result.get('ok') else (403 if result.get('error') == 'forbidden' else 400)
    return JsonResponse(result, status=status)


@csrf_exempt
@require_http_methods(['PATCH'])
def umnik_deal_cost(request, deal_id):
    user = _actor(request)
    if user is None:
        return _deny()
    deal = umnik_actions.find_deal(deal_id=deal_id)
    if deal is None:
        return JsonResponse({'ok': False, 'error': 'deal not found'}, status=404)
    result = umnik_actions.update_cost(deal, user, _json_body(request))
    status = 200 if result.get('ok') else (403 if result.get('error') == 'forbidden' else 400)
    return JsonResponse(result, status=status)
