from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from accounts.forms import EmployeeCreateForm, EmployeeUpdateForm
from catalog.models import CostItem, CostItemOption, Section
from core.views import _section_uses_module_groups, _section_uses_supplier_tabs
from deals.models import LibraryAsset
from system_settings.events import TOP_DOMAIN_EVENTS
from system_settings.services import DEFAULT_SYSTEM_CONFIG, get_system_config_value, set_system_config_value

from .decorators import leadership_required
from .forms import CatalogItemForm, CatalogOptionAdminForm, IntegrationTokenCreateForm, SystemConfigForm
from .forms import SYSTEM_CONFIG_LABELS
from .models import IntegrationToken, PlatformJob, SystemConfig


@login_required
@leadership_required
def settings_home(_request):
    return redirect('settings_employees')


@login_required
@leadership_required
@require_http_methods(['GET', 'POST'])
def settings_employees(request):
    user_model = get_user_model()
    create_form = EmployeeCreateForm()
    update_forms = {
        employee.id: EmployeeUpdateForm(instance=employee)
        for employee in user_model.objects.order_by('username')
    }

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        if action == 'create':
            create_form = EmployeeCreateForm(request.POST)
            if create_form.is_valid():
                create_form.save()
                return redirect('settings_employees')
        elif action == 'update':
            employee_id = request.POST.get('employee_id', '').strip()
            if not employee_id.isdigit():
                return HttpResponseBadRequest('Invalid employee id')
            employee = get_object_or_404(user_model, pk=int(employee_id))
            update_form = EmployeeUpdateForm(request.POST, instance=employee)
            if update_form.is_valid():
                proposed_role = update_form.cleaned_data['role']
                proposed_active = update_form.cleaned_data['is_active']
                if employee.id == request.user.id and (
                    proposed_role not in {'head', 'admin'} or not proposed_active
                ):
                    return HttpResponseBadRequest('Cannot remove your own leadership access')
                leadership_count = user_model.objects.filter(
                    role__in=['head', 'admin'],
                    is_active=True,
                ).count()
                if employee.role in {'head', 'admin'} and employee.is_active:
                    if proposed_role not in {'head', 'admin'} or not proposed_active:
                        if leadership_count <= 1:
                            return HttpResponseBadRequest('Cannot remove last leadership user')
                update_form.save()
                return redirect('settings_employees')
            update_forms[employee.id] = update_form

    employees = user_model.objects.order_by('username')
    return render(
        request,
        'system_settings/employees.html',
        {
            'settings_section': 'employees',
            'employees': employees,
            'employee_create_form': create_form,
            'employee_update_forms': update_forms,
        },
    )


@login_required
@leadership_required
def settings_library(request):
    section_labels = {
        LibraryAsset.Section.LAYOUT: 'Планировки',
        LibraryAsset.Section.CONTRACT_TEMPLATE: 'Шаблоны договоров',
        LibraryAsset.Section.PHOTO: 'Фото',
        LibraryAsset.Section.VIDEO: 'Видео',
        LibraryAsset.Section.SUPPLIER_FILE: 'Файлы поставщиков',
    }
    module_tabs = list(LibraryAsset.ModuleGroup.choices)
    supplier_tabs = list(LibraryAsset.SupplierCategory.choices)
    active_section = request.GET.get('section', LibraryAsset.Section.LAYOUT)
    active_module_group = request.GET.get('module_group', LibraryAsset.ModuleGroup.M1)
    active_supplier_category = request.GET.get(
        'supplier_category',
        LibraryAsset.SupplierCategory.FINISHING,
    )
    valid_sections = {value for value, _ in LibraryAsset.Section.choices}
    valid_groups = {value for value, _ in LibraryAsset.ModuleGroup.choices}
    valid_supplier_categories = {value for value, _ in LibraryAsset.SupplierCategory.choices}

    if active_section not in valid_sections:
        active_section = LibraryAsset.Section.LAYOUT
    if active_module_group not in valid_groups:
        active_module_group = LibraryAsset.ModuleGroup.M1
    if active_supplier_category not in valid_supplier_categories:
        active_supplier_category = LibraryAsset.SupplierCategory.FINISHING

    uses_module_groups = _section_uses_module_groups(active_section)
    uses_supplier_tabs = _section_uses_supplier_tabs(active_section)
    if not uses_module_groups:
        active_module_group = LibraryAsset.ModuleGroup.M1
    if not uses_supplier_tabs:
        active_supplier_category = LibraryAsset.SupplierCategory.FINISHING

    assets_qs = LibraryAsset.objects.filter(section=active_section)
    if uses_module_groups:
        assets_qs = assets_qs.filter(module_group=active_module_group)
    if uses_supplier_tabs:
        assets_qs = assets_qs.filter(supplier_category=active_supplier_category)

    return render(
        request,
        'system_settings/library.html',
        {
            'settings_section': 'library',
            'section_labels': section_labels,
            'active_section_label': section_labels.get(active_section, 'Файлы'),
            'module_tabs': module_tabs,
            'supplier_tabs': supplier_tabs,
            'active_section': active_section,
            'active_module_group': active_module_group,
            'active_supplier_category': active_supplier_category,
            'uses_module_groups': uses_module_groups,
            'uses_supplier_tabs': uses_supplier_tabs,
            'assets': list(assets_qs.order_by('-updated_at')),
            'image_exts': {'jpg', 'jpeg', 'png', 'webp', 'gif'},
            'upload_error': request.GET.get('error', '').strip(),
            'redirect_to': reverse('settings_library'),
        },
    )


@login_required
@leadership_required
def settings_catalog(request):
    search_query = (request.GET.get('q') or '').strip()
    section_code = (request.GET.get('section') or '').strip()
    category = (request.GET.get('category') or '').strip()

    items = CostItem.objects.select_related('section').annotate(
        options_count=Count('options'),
    )
    if search_query:
        items = items.filter(
            Q(name_ru__icontains=search_query) | Q(code__icontains=search_query),
        )
    if section_code:
        items = items.filter(section__code=section_code)
    if category:
        items = items.filter(category=category)

    query_string = urlencode(
        {
            key: value
            for key, value in {
                'q': search_query,
                'section': section_code,
                'category': category,
            }.items()
            if value
        },
    )

    return render(
        request,
        'system_settings/catalog_list.html',
        {
            'settings_section': 'catalog',
            'items': items.order_by('category', 'sort_order', 'name_ru'),
            'sections': Section.objects.order_by('sort_order', 'code'),
            'category_choices': CostItem.Category.choices,
            'selected_section': section_code,
            'selected_category': category,
            'search_query': search_query,
            'query_string': query_string,
        },
    )


@login_required
@leadership_required
@require_http_methods(['GET', 'POST'])
def settings_catalog_item_create(request):
    item = None
    item_form = CatalogItemForm(request.POST or None)
    if request.method == 'POST' and item_form.is_valid():
        item = item_form.save()
        return redirect('settings_catalog_item_detail', item_id=item.id)
    return render(
        request,
        'system_settings/catalog_detail.html',
        {
            'settings_section': 'catalog',
            'item': item,
            'item_form': item_form,
            'option_form': CatalogOptionAdminForm(),
            'options': [],
            'page_title': 'Новая позиция каталога',
        },
    )


@login_required
@leadership_required
@require_http_methods(['GET', 'POST'])
def settings_catalog_item_detail(request, item_id):
    item = get_object_or_404(CostItem.objects.select_related('section'), pk=item_id)
    item_form = CatalogItemForm(request.POST or None, instance=item)
    option_form = CatalogOptionAdminForm()

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        if action == 'save_item':
            if item_form.is_valid():
                item_form.save()
                return redirect('settings_catalog_item_detail', item_id=item.id)
        elif action == 'create_option':
            option_form = CatalogOptionAdminForm(request.POST)
            if option_form.is_valid():
                option = option_form.save(commit=False)
                option.cost_item = item
                if not option.unit:
                    option.unit = item.unit
                option.save()
                return redirect('settings_catalog_item_detail', item_id=item.id)

    return render(
        request,
        'system_settings/catalog_detail.html',
        {
            'settings_section': 'catalog',
            'item': item,
            'item_form': item_form,
            'option_form': option_form,
            'options': item.options.order_by('sort_order', 'name_ru'),
            'option_update_forms': {
                option.id: CatalogOptionAdminForm(instance=option)
                for option in item.options.order_by('sort_order', 'name_ru')
            },
            'page_title': f'Каталог: {item.name_ru}',
        },
    )


@login_required
@leadership_required
@require_POST
def settings_catalog_option_update(request, option_id):
    option = get_object_or_404(
        CostItemOption.objects.select_related('cost_item'),
        pk=option_id,
    )
    form = CatalogOptionAdminForm(request.POST, instance=option)
    if form.is_valid():
        updated = form.save(commit=False)
        if not updated.unit:
            updated.unit = option.cost_item.unit
        updated.save()
    return redirect('settings_catalog_item_detail', item_id=option.cost_item_id)


@login_required
@leadership_required
@require_http_methods(['GET', 'POST'])
def settings_business(request):
    initial = {
        'default_margin_percent': get_system_config_value(
            SystemConfig.Key.DEFAULT_MARGIN_PERCENT,
            DEFAULT_SYSTEM_CONFIG[SystemConfig.Key.DEFAULT_MARGIN_PERCENT],
        ),
        'stale_deal_days': get_system_config_value(
            SystemConfig.Key.STALE_DEAL_DAYS,
            DEFAULT_SYSTEM_CONFIG[SystemConfig.Key.STALE_DEAL_DAYS],
        ),
        'task_reminder_hours': get_system_config_value(
            SystemConfig.Key.TASK_REMINDER_HOURS,
            DEFAULT_SYSTEM_CONFIG[SystemConfig.Key.TASK_REMINDER_HOURS],
        ),
    }
    form = SystemConfigForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        set_system_config_value(
            key=SystemConfig.Key.DEFAULT_MARGIN_PERCENT,
            value=str(form.cleaned_data['default_margin_percent']),
            user=request.user,
        )
        set_system_config_value(
            key=SystemConfig.Key.STALE_DEAL_DAYS,
            value=str(form.cleaned_data['stale_deal_days']),
            user=request.user,
        )
        set_system_config_value(
            key=SystemConfig.Key.TASK_REMINDER_HOURS,
            value=str(form.cleaned_data['task_reminder_hours']),
            user=request.user,
        )
        return redirect('settings_business')

    configs = SystemConfig.objects.select_related('updated_by').order_by('key')
    return render(
        request,
        'system_settings/business.html',
        {
            'settings_section': 'business',
            'form': form,
            'configs': configs,
            'config_labels': SYSTEM_CONFIG_LABELS,
        },
    )


@login_required
@leadership_required
@require_http_methods(['GET', 'POST'])
def settings_integrations(request):
    form = IntegrationTokenCreateForm(request.POST or None)
    created_token = ''
    if request.method == 'POST' and form.is_valid():
        token = IntegrationToken.create_token(
            name=form.cleaned_data['name'],
            owner=form.cleaned_data['owner'],
            created_by=request.user,
        )
        created_token = token.key
        form = IntegrationTokenCreateForm()

    return render(
        request,
        'system_settings/integrations.html',
        {
            'settings_section': 'integrations',
            'form': form,
            'created_token': created_token,
            'integration_tokens': IntegrationToken.objects.select_related(
                'owner',
                'created_by',
            ).order_by('name', '-created_at'),
            'plugin_endpoint': request.build_absolute_uri(
                reverse('plugin_project_versions_create'),
            ),
            'domain_events': TOP_DOMAIN_EVENTS,
            'platform_jobs': PlatformJob.objects.order_by('-created_at')[:20],
        },
    )


@login_required
@leadership_required
@require_POST
def settings_integration_token_delete(request, token_id):
    token = get_object_or_404(IntegrationToken, pk=token_id)
    token.delete()
    return redirect('settings_integrations')
