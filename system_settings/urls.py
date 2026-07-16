from django.urls import path

from .views import (
    settings_business,
    settings_catalog,
    settings_catalog_item_create,
    settings_catalog_item_detail,
    settings_catalog_option_update,
    settings_employees,
    settings_home,
    settings_integrations,
    settings_integration_token_delete,
    settings_library,
)


urlpatterns = [
    path('', settings_home, name='settings_home'),
    path('employees/', settings_employees, name='settings_employees'),
    path('library/', settings_library, name='settings_library'),
    path('catalog/', settings_catalog, name='settings_catalog'),
    path('catalog/items/new/', settings_catalog_item_create, name='settings_catalog_item_create'),
    path('catalog/items/<int:item_id>/', settings_catalog_item_detail, name='settings_catalog_item_detail'),
    path(
        'catalog/options/<int:option_id>/update/',
        settings_catalog_option_update,
        name='settings_catalog_option_update',
    ),
    path('business/', settings_business, name='settings_business'),
    path('integrations/', settings_integrations, name='settings_integrations'),
    path(
        'integrations/tokens/<int:token_id>/delete/',
        settings_integration_token_delete,
        name='settings_integration_token_delete',
    ),
]
