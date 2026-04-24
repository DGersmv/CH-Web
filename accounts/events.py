from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from accounts.models import AuditEvent, Notification


def _request_meta(request):
    if request is None:
        return '', ''
    return request.META.get('REMOTE_ADDR', ''), request.META.get('HTTP_USER_AGENT', '')[:512]


def log_audit_event(*, actor, event_type, entity_model, entity_id=None, payload=None, request=None):
    ip_address, user_agent = _request_meta(request)
    return AuditEvent.objects.create(
        actor=actor,
        event_type=event_type,
        entity_model=entity_model,
        entity_id=entity_id,
        payload=payload or {},
        ip_address=ip_address,
        user_agent=user_agent,
    )


def create_notification(*, user, actor, notification_type, title, body='', related_model='', related_id=None):
    notification = Notification.objects.create(
        user=user,
        actor=actor,
        notification_type=notification_type,
        title=title,
        body=body,
        related_model=related_model,
        related_id=related_id,
    )
    push_user_event(
        user_id=user.id,
        payload={
            'type': 'notification.created',
            'notification': {
                'id': notification.id,
                'title': notification.title,
                'body': notification.body,
                'notification_type': notification.notification_type,
                'created_at': notification.created_at.isoformat(),
            },
        },
    )
    return notification


def push_user_event(*, user_id, payload):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        f'user_{user_id}_events',
        {
            'type': 'notify',
            'payload': payload,
        },
    )
