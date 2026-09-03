"""Чек-лист согласований по сделке: дефолтные пункты, досев, сводка гейта."""

from deals.models import DealApproval, ProjectVersion


DEFAULT_APPROVAL_ITEMS = [
    {
        'slug': 'layout',
        'title': 'Планировка',
        'hint': 'Привязка к конкретной версии проекта',
        'is_required': True,
    },
    {
        'slug': 'cost_quote',
        'title': 'Стоимость / КП',
        'hint': 'Что входит в цену, что идёт опцией',
        'is_required': True,
    },
    {
        'slug': 'bathrooms',
        'title': 'Комплектация санузлов',
        'hint': 'Сантехника, плитка, разводка по каждому санузлу',
        'is_required': True,
    },
    {
        'slug': 'electrical',
        'title': 'Электрика',
        'hint': 'Схема электрощита, розетки/выключатели, слаботочка, ввод и мощность',
        'is_required': True,
    },
    {
        'slug': 'additional_options',
        'title': 'Дополнительные опции',
        'hint': 'Терраса, навес, инженерка и прочие допы',
        'is_required': True,
    },
    {
        'slug': 'finishing',
        'title': 'Отделка / материалы',
        'hint': 'Фасад, внутренняя отделка, материалы',
        'is_required': True,
    },
    {
        'slug': 'site',
        'title': 'Участок, подъездные пути, площадка под монтаж',
        'hint': 'Доступ техники, место под кран и модули',
        'is_required': True,
    },
    {
        'slug': 'foundation_geology',
        'title': 'Фундамент / геология',
        'hint': 'Тип фундамента, результаты геологии',
        'is_required': True,
    },
    {
        'slug': 'timeline',
        'title': 'Сроки и график',
        'hint': 'График производства, доставки и монтажа',
        'is_required': True,
    },
    {
        'slug': 'contract_data',
        'title': 'Данные для договора',
        'hint': 'Паспорт, реквизиты; ипотека — нужна ли, одобрение банка',
        'is_required': True,
    },
]

DEFAULT_APPROVAL_BY_SLUG = {item['slug']: item for item in DEFAULT_APPROVAL_ITEMS}


def ensure_deal_approvals(deal):
    """Досевает недостающие пункты чек-листа и синхронизирует шаблонные."""
    existing = {a.slug: a for a in deal.approvals.all()}
    to_create = []
    to_update = []
    for index, item in enumerate(DEFAULT_APPROVAL_ITEMS):
        current = existing.get(item['slug'])
        if current is None:
            to_create.append(
                DealApproval(
                    deal=deal,
                    slug=item['slug'],
                    title=item['title'],
                    hint=item['hint'],
                    is_required=item['is_required'],
                    sort_order=index,
                )
            )
            continue
        # шаблонные пункты держим в актуальном виде, пользовательские не трогаем
        if not current.is_custom:
            changed = False
            if current.title != item['title']:
                current.title = item['title']
                changed = True
            if current.hint != item['hint']:
                current.hint = item['hint']
                changed = True
            if current.sort_order != index:
                current.sort_order = index
                changed = True
            if changed:
                to_update.append(current)
    if to_create:
        DealApproval.objects.bulk_create(to_create)
    if to_update:
        DealApproval.objects.bulk_update(to_update, ['title', 'hint', 'sort_order'])
    return list(deal.approvals.select_related('decided_by', 'project_version').all())


def approvals_gate(items):
    """Сводка по гейту этапа «Согласования»."""
    required = [i for i in items if i.is_required]
    blocking = [i for i in required if not i.is_satisfied]
    return {
        'required_total': len(required),
        'required_satisfied': len(required) - len(blocking),
        'blocking': blocking,
        'passed': not blocking,
    }


def build_approvals_context(deal):
    """Общий контекст для карточки сделки и htmx-партиала чек-листа."""
    items = ensure_deal_approvals(deal)
    versions = list(
        ProjectVersion.objects.filter(deal=deal)
        .select_related('created_by')
        .order_by('-version_number')
    )
    accepted_version = next(
        (v for v in versions if v.status == ProjectVersion.Status.ACCEPTED),
        None,
    )
    by_slug = {i.slug: i for i in items}
    layout_item = by_slug.get('layout')
    layout_latest_file = None
    if layout_item is not None:
        layout_latest_file = (
            layout_item.files.filter(is_archived=False)
            .order_by('-created_at')
            .first()
        )
    return {
        'deal': deal,
        'approvals_list': items,
        'approvals_by_slug': by_slug,
        'layout_approval': layout_item,
        'layout_latest_file': layout_latest_file,
        'approvals_gate': approvals_gate(items),
        'versions': versions,
        'approvals_accepted_version': accepted_version,
        'approval_status_choices': DealApproval.Status.choices,
    }
