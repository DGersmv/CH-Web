from django.urls import path

from . import views

urlpatterns = [
    path('', views.room_list, name='list'),
    path('new/', views.room_new, name='new'),
    path('contacts/', views.room_contacts, name='contacts'),
    path('calls/', views.room_calls, name='calls'),
    path('settings/', views.room_settings, name='settings'),
    path('with/umnik/', views.room_open_umnik, name='with_umnik'),
    path('with/<int:user_id>/', views.room_open_user, name='with_user'),
    path('install/', views.app_install, name='install'),
    path('<int:room_id>/', views.room_detail, name='detail'),
    path('<int:room_id>/messages/', views.room_messages, name='messages'),
    path('<int:room_id>/send/', views.room_send, name='send'),
    path('<int:room_id>/umnik/', views.room_toggle_umnik, name='umnik'),
    path('<int:room_id>/files/<int:att_id>/', views.room_file, name='file'),
]
