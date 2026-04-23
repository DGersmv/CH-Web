"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from deals.views import (
    DealCreateView,
    claim_lead,
    recalc_configurator,
    save_configurator_draft,
    update_deal_manager,
    update_deal_margin,
    update_deal_status,
)
from .views import DealDetailView, DealListView, clients_page, global_search, home
from tasks.views import TaskListView, create_task_for_deal, toggle_task

urlpatterns = [
    path('', home, name='home'),
    path('search/global/', global_search, name='global_search'),
    path('deals/', DealListView.as_view(), name='deals'),
    path('deals/new/', DealCreateView.as_view(), name='deal_create'),
    path('deals/<int:pk>/', DealDetailView.as_view(), name='deal_detail'),
    path('deals/<int:deal_id>/status/', update_deal_status, name='deal_status_update'),
    path('deals/<int:deal_id>/manager/', update_deal_manager, name='deal_manager_update'),
    path('deals/<int:deal_id>/margin/', update_deal_margin, name='deal_margin_update'),
    path('deals/<int:deal_id>/tasks/new/', create_task_for_deal, name='deal_task_create'),
    path('deals/<int:deal_id>/config/recalc/', recalc_configurator, name='config_recalc'),
    path('deals/<int:deal_id>/config/save/', save_configurator_draft, name='config_save'),
    path('dashboard/leads/<int:deal_id>/claim/', claim_lead, name='dashboard_claim_lead'),
    path('tasks/<int:task_id>/toggle/', toggle_task, name='task_toggle'),
    path('tasks/', TaskListView.as_view(), name='tasks'),
    path('clients/', clients_page, name='clients'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('admin/', admin.site.urls),
]
