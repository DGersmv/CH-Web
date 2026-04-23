from decimal import Decimal, InvalidOperation
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import DetailView, ListView

from clients.models import Client
from deals.forms import DealConfiguratorForm
from deals.models import ChangeLog, Deal, ProjectVersion
from deals.services.calculation_engine import calculate_config
from tasks.models import Task


@login_required
def home(request):
    today = timezone.localdate()
    active_statuses = [Deal.Status.NEW, Deal.Status.QUALIFIED, Deal.Status.SENT_QUOTE, Deal.Status.CONTRACT, Deal.Status.PREPAYMENT, Deal.Status.PRODUCTION, Deal.Status.INSTALLATION]
    my_active_deals = (
        Deal.objects.select_related('client')
        .filter(assigned_manager=request.user, status__in=active_statuses)
        .order_by('-updated_at')
    )
    urgent_tasks = (
        Task.objects.select_related('deal')
        .filter(assignee=request.user, is_done=False, due_date__lte=today)
        .order_by('due_date', 'created_at')
    )
    archicad_updates = (
        ProjectVersion.objects.select_related('deal', 'created_by')
        .filter(source=ProjectVersion.Source.ARCHICAD)
        .order_by('-created_at')[:10]
    )
    stale_deals = (
        Deal.objects.select_related('client', 'assigned_manager')
        .exclude(status__in=[Deal.Status.DELIVERED, Deal.Status.LOST])
        .filter(updated_at__lt=timezone.now() - timedelta(days=7))
        .order_by('updated_at')
    )
    for deal in stale_deals:
        deal.silent_days = max((today - deal.updated_at.date()).days, 0)
    new_leads = (
        Deal.objects.select_related('client')
        .filter(assigned_manager__isnull=True, status__in=[Deal.Status.ORPHAN, Deal.Status.NEW])
        .order_by('-created_at')
    )

    context = {
        'my_active_deals': my_active_deals,
        'urgent_tasks': urgent_tasks,
        'archicad_updates': archicad_updates,
        'stale_deals': stale_deals,
        'new_leads': new_leads,
        'today': today,
    }

    if getattr(request.user, 'role', None) == 'head':
        context['pipeline_total'] = Deal.objects.exclude(status__in=[Deal.Status.DELIVERED, Deal.Status.LOST]).count()
        context['stale_deals_count'] = Deal.objects.filter(updated_at__lt=timezone.now() - timedelta(days=7)).count()

    return render(request, 'home.html', context)


@login_required
def deals_page(request):
    return render(request, 'deal_list.html')


@login_required
def tasks_page(request):
    return render(request, 'task_list.html')


@login_required
def clients_page(request):
    return render(request, 'client_list.html')


@login_required
def global_search(request):
    query = request.GET.get('q', '').strip()
    if not query:
        return render(request, 'includes/global_search_results.html', {'query': '', 'results': []})

    deal_results = (
        Deal.objects.select_related('client')
        .filter(project_code__icontains=query)
        .order_by('-updated_at')[:5]
    )
    client_matches = (
        Client.objects.prefetch_related('deals')
        .filter(full_name__icontains=query)
        .order_by('full_name')[:5]
    )

    results = []
    for deal in deal_results:
        results.append(
            {
                'type': 'deal',
                'label': f'{deal.project_code}',
                'subtitle': f'Клиент: {deal.client.full_name}' if deal.client else 'Клиент не указан',
                'url': reverse('deal_detail', kwargs={'pk': deal.pk}),
            }
        )

    for client in client_matches:
        target_deal = client.deals.order_by('-updated_at').first()
        if target_deal:
            url = reverse('deal_detail', kwargs={'pk': target_deal.pk})
            subtitle = f'Клиент -> сделка {target_deal.project_code}'
        else:
            url = reverse('clients')
            subtitle = 'Клиент (без сделок)'
        results.append(
            {
                'type': 'client',
                'label': client.full_name,
                'subtitle': subtitle,
                'url': url,
            }
        )

    return render(request, 'includes/global_search_results.html', {'query': query, 'results': results[:10]})


class DealListView(LoginRequiredMixin, ListView):
    model = Deal
    template_name = 'deal_list.html'
    context_object_name = 'deals'
    paginate_by = 25

    def get_queryset(self):
        queryset = (
            Deal.objects.select_related('client', 'assigned_manager')
            .prefetch_related(
                Prefetch(
                    'versions',
                    queryset=ProjectVersion.objects.order_by('-version_number'),
                    to_attr='versions_for_list',
                )
            )
            .order_by('-updated_at')
        )
        status = self.request.GET.get('status', '').strip()
        module_count = self.request.GET.get('module_count', '').strip()
        manager_id = self.request.GET.get('assigned_manager', '').strip()
        mine = self.request.GET.get('mine', '').strip()
        search = self.request.GET.get('q', '').strip()

        if status and status in dict(Deal.Status.choices):
            queryset = queryset.filter(status=status)

        if module_count.isdigit():
            queryset = queryset.filter(module_count=int(module_count))

        if manager_id.isdigit():
            queryset = queryset.filter(assigned_manager_id=int(manager_id))

        if mine == '1':
            queryset = queryset.filter(assigned_manager=self.request.user)

        if search:
            queryset = queryset.filter(
                Q(project_code__icontains=search)
                | Q(client__full_name__icontains=search)
                | Q(client__phone__icontains=search)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_status = self.request.GET.get('status', '').strip()
        selected_module_count = self.request.GET.get('module_count', '').strip()
        selected_manager = self.request.GET.get('assigned_manager', '').strip()
        selected_mine = self.request.GET.get('mine', '').strip()
        search_query = self.request.GET.get('q', '').strip()

        for deal in context['deals']:
            latest_version = deal.versions_for_list[0] if deal.versions_for_list else None
            deal.latest_total = self._extract_total(latest_version)

        context['status_choices'] = Deal.Status.choices
        context['module_choices'] = [3, 5, 7, 9, 11]
        context['manager_choices'] = (
            self.request.user.__class__.objects.filter(role='manager').order_by('username')
        )
        context['selected_status'] = selected_status
        context['selected_module_count'] = selected_module_count
        context['selected_manager'] = selected_manager
        context['selected_mine'] = selected_mine == '1'
        context['search_query'] = search_query
        context['current_filters'] = self._build_filter_query_without_page()
        return context

    def _build_filter_query_without_page(self):
        params = self.request.GET.copy()
        params.pop('page', None)
        return params.urlencode()

    @staticmethod
    def _extract_total(version):
        if not version or not version.frozen_data:
            return None
        data = version.frozen_data
        candidates = (
            ('total_amount',),
            ('total',),
            ('summary', 'total'),
            ('totals', 'grand_total'),
            ('totals', 'total'),
            ('price', 'total'),
        )
        for path in candidates:
            value = data
            for key in path:
                if not isinstance(value, dict) or key not in value:
                    value = None
                    break
                value = value[key]
            if value is None:
                continue
            try:
                return Decimal(str(value))
            except (InvalidOperation, ValueError, TypeError):
                continue
        return None


class DealDetailView(LoginRequiredMixin, DetailView):
    model = Deal
    template_name = 'deal_detail.html'
    context_object_name = 'deal'

    def get_queryset(self):
        return (
            Deal.objects.select_related('client', 'assigned_manager')
            .prefetch_related(
                Prefetch('versions', queryset=ProjectVersion.objects.select_related('created_by').order_by('-version_number')),
                Prefetch('tasks', queryset=self._task_queryset()),
            )
        )

    def _task_queryset(self):
        from tasks.models import Task

        return Task.objects.select_related('assignee').order_by('is_done', 'due_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        draft_version = self.object.versions.filter(status=ProjectVersion.Status.DRAFT).order_by('-version_number').first()
        if draft_version is None:
            draft_version = self.object.create_new_version(source='manual', created_by=self.request.user)
        frozen = draft_version.frozen_data or {}
        config_inputs = frozen.get('config_inputs')
        config_form = DealConfiguratorForm(initial=config_inputs) if config_inputs else DealConfiguratorForm(
            initial={
                'building_area': '120',
                'living_area': '90',
                'ceiling_height': '2.7',
                'floor_insulation': '200',
                'roof_type': 'gable',
                'windows_count': 8,
                'sauna_cost': '0',
            }
        )
        calc_result = frozen.get('calculation')
        if calc_result is None:
            calc_result = calculate_config(config_form.initial, margin_percent=self.object.margin_percent)

        context['versions'] = self.object.versions.all()
        context['tasks_for_deal'] = self.object.tasks.all()
        context['status_choices'] = Deal.Status.choices
        context['manager_choices'] = self.request.user.__class__.objects.filter(role='manager').order_by('username')
        context['draft_version'] = draft_version
        context['config_form'] = config_form
        context['calc_result'] = calc_result
        context['save_success'] = False
        context['change_logs'] = ChangeLog.objects.filter(project_version__deal=self.object).select_related(
            'project_version', 'changed_by'
        )[:20]
        return context
