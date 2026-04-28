import time

from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from accounts.permissions import is_file_only_role

from .forms import CostItemOptionForm
from .models import CostItem, CostItemOption


def _option_json(opt):
    return {
        'id': opt.id,
        'name_ru': opt.name_ru,
        'price': str(opt.price),
        'unit': opt.unit or '',
        'manufacturer': opt.manufacturer or '',
        'article': opt.article or '',
        'country': opt.country or '',
        'description': opt.description or '',
    }


@login_required
@require_POST
def create_cost_item_option(request, cost_item_id):
    """Создаёт CostItemOption для наименования каталога; ответ JSON для обновления select на странице санузла."""
    if is_file_only_role(request.user):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    cost_item = get_object_or_404(CostItem, pk=cost_item_id)
    form = CostItemOptionForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': form.errors}, status=400)

    opt = form.save(commit=False)
    opt.cost_item = cost_item
    opt.code = f'opt-{cost_item.id}-{int(time.time())}'
    max_so = CostItemOption.objects.filter(cost_item=cost_item).aggregate(m=Max('sort_order'))['m']
    opt.sort_order = (max_so or 0) + 10
    opt.is_active = True
    opt.is_default = False
    if not opt.unit:
        opt.unit = cost_item.unit
    opt.save()

    return JsonResponse({'ok': True, 'option': _option_json(opt)})


@login_required
@require_POST
def update_cost_item_option(request, option_id):
    """Редактирует существующую модель; ответ JSON для обновления текущего select."""
    if is_file_only_role(request.user):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    opt = get_object_or_404(CostItemOption, pk=option_id)
    form = CostItemOptionForm(request.POST, instance=opt)
    if not form.is_valid():
        return JsonResponse({'ok': False, 'errors': form.errors}, status=400)

    opt = form.save(commit=False)
    if not opt.unit:
        opt.unit = opt.cost_item.unit
    opt.save()
    return JsonResponse({'ok': True, 'option': _option_json(opt)})
