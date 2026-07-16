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
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from deals.api_views import PluginProjectVersionCreateApi
from .api_views import DirectMessageListCreateApi, DirectMessageReadApi, NotificationListApi, NotificationReadAllApi
from catalog.views import create_cost_item_option, update_cost_item_option
from deals.views import (
    archive_project_file,
    bathrooms_page,
    additional_options_page,
    bulk_project_file_action,
    cost_summary_page,
    create_dashboard_lead,
    DealCreateView,
    claim_lead,
    create_additional_option,
    open_project_file,
    recalc_configurator,
    save_bathroom_tab,
    save_additional_options,
    save_configurator_draft,
    update_deal_cost_summary,
    update_deal_module_count,
    upload_project_file,
    update_deal_manager,
    update_deal_margin,
    update_deal_status,
    client_portal_chat,
    client_portal_entry,
    client_portal_message_send,
    client_portal_open_project_file,
    client_portal_send_otp,
    client_portal_upload,
    deal_client_message_attach_existing,
    deal_client_message_send,
    deal_client_message_upload,
)
from .views import (
    DealDetailView,
    DealListView,
    client_create,
    client_edit,
    clients_page,
    files_page,
    dashboard_employee_create,
    dashboard_message_send,
    dashboard_employee_update,
    library_asset_download,
    library_asset_upload,
    notifications_mark_all_read,
    global_search,
    home,
    logout_and_redirect,
)
from tasks.views import TaskListView, create_task_for_deal, open_task_file, toggle_task

urlpatterns = [
    path('', home, name='home'),
    path('settings/', include('system_settings.urls')),
    path('api/plugin/project-versions/', PluginProjectVersionCreateApi.as_view(), name='plugin_project_versions_create'),
    path('api/messages/', DirectMessageListCreateApi.as_view(), name='api_messages'),
    path('api/messages/<int:message_id>/read/', DirectMessageReadApi.as_view(), name='api_message_read'),
    path('api/notifications/', NotificationListApi.as_view(), name='api_notifications'),
    path('api/notifications/read-all/', NotificationReadAllApi.as_view(), name='api_notifications_read_all'),
    path('search/global/', global_search, name='global_search'),
    path('deals/', DealListView.as_view(), name='deals'),
    path('deals/new/', DealCreateView.as_view(), name='deal_create'),
    path('deals/<int:pk>/', DealDetailView.as_view(), name='deal_detail'),
    path('deals/<int:deal_id>/status/', update_deal_status, name='deal_status_update'),
    path('deals/<int:deal_id>/manager/', update_deal_manager, name='deal_manager_update'),
    path('deals/<int:deal_id>/module-count/', update_deal_module_count, name='deal_module_update'),
    path('deals/<int:deal_id>/margin/', update_deal_margin, name='deal_margin_update'),
    path('deals/<int:deal_id>/tasks/new/', create_task_for_deal, name='deal_task_create'),
    path('deals/<int:deal_id>/config/recalc/', recalc_configurator, name='config_recalc'),
    path('deals/<int:deal_id>/config/save/', save_configurator_draft, name='config_save'),
    path('deals/<int:deal_id>/cost-summary/', cost_summary_page, name='deal_cost_summary_page'),
    path('deals/<int:deal_id>/bathrooms/', bathrooms_page, name='deal_bathrooms_page'),
    path('deals/<int:deal_id>/bathrooms/<int:bathroom_id>/save/', save_bathroom_tab, name='deal_bathroom_tab_save'),
    path('deals/<int:deal_id>/additional-options/', additional_options_page, name='deal_additional_options_page'),
    path('deals/<int:deal_id>/additional-options/save/', save_additional_options, name='deal_additional_options_save'),
    path('deals/<int:deal_id>/additional-options/create/', create_additional_option, name='deal_additional_options_create'),
    path(
        'catalog/cost-items/<int:cost_item_id>/options/create/',
        create_cost_item_option,
        name='cost_item_option_create',
    ),
    path('catalog/options/<int:option_id>/update/', update_cost_item_option, name='cost_item_option_update'),
    path('deals/<int:deal_id>/cost-summary/update/', update_deal_cost_summary, name='deal_cost_summary_update'),
    path('deals/<int:deal_id>/files/upload/', upload_project_file, name='deal_file_upload'),
    path('deals/<int:deal_id>/files/<str:source>/bulk/', bulk_project_file_action, name='deal_file_bulk_action'),
    path('deals/files/<int:file_id>/open/', open_project_file, name='deal_file_open'),
    path('deals/files/<int:file_id>/archive/', archive_project_file, name='deal_file_archive'),
    path('deals/<int:deal_id>/client-portal/', client_portal_entry, name='client_portal_entry'),
    path('deals/<int:deal_id>/client-portal/send-otp/', client_portal_send_otp, name='client_portal_send_otp'),
    path('deals/<int:deal_id>/client-portal/chat/', client_portal_chat, name='client_portal_chat'),
    path('deals/<int:deal_id>/client-portal/messages/send/', client_portal_message_send, name='client_portal_message_send'),
    path('deals/<int:deal_id>/client-portal/messages/upload/', client_portal_upload, name='client_portal_upload'),
    path('deals/<int:deal_id>/client-portal/files/<int:file_id>/open/', client_portal_open_project_file, name='client_portal_file_open'),
    path('deals/<int:deal_id>/client-messages/send/', deal_client_message_send, name='deal_client_message_send'),
    path('deals/<int:deal_id>/client-messages/attach-existing/', deal_client_message_attach_existing, name='deal_client_message_attach_existing'),
    path('deals/<int:deal_id>/client-messages/upload/', deal_client_message_upload, name='deal_client_message_upload'),
    path('dashboard/leads/<int:deal_id>/claim/', claim_lead, name='dashboard_claim_lead'),
    path('dashboard/leads/create/', create_dashboard_lead, name='dashboard_lead_create'),
    path('dashboard/employees/create/', dashboard_employee_create, name='dashboard_employee_create'),
    path('dashboard/employees/<int:user_id>/update/', dashboard_employee_update, name='dashboard_employee_update'),
    path('dashboard/messages/send/', dashboard_message_send, name='dashboard_message_send'),
    path('dashboard/notifications/read-all/', notifications_mark_all_read, name='notifications_mark_all_read'),
    path('tasks/<int:task_id>/toggle/', toggle_task, name='task_toggle'),
    path('tasks/<int:task_id>/file/open/', open_task_file, name='task_file_open'),
    path('tasks/', TaskListView.as_view(), name='tasks'),
    path('clients/', clients_page, name='clients'),
    path('files/', files_page, name='files'),
    path('files/upload/', library_asset_upload, name='library_asset_upload'),
    path('files/assets/<int:asset_id>/download/', library_asset_download, name='library_asset_download'),
    path('clients/new/', client_create, name='client_create'),
    path('clients/<int:pk>/edit/', client_edit, name='client_edit'),
    path('accounts/logout/', logout_and_redirect, name='logout'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
