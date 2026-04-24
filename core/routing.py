from django.urls import re_path

from accounts.consumers import UserEventsConsumer


websocket_urlpatterns = [
    re_path(r'^ws/events/$', UserEventsConsumer.as_asgi()),
]
