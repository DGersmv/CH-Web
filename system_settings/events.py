from accounts.events import log_audit_event

from .services import enqueue_platform_job


TOP_DOMAIN_EVENTS = (
    'deal.status_changed',
    'project_version.imported',
    'project_file.uploaded',
    'task.created',
    'client_message.sent',
)


def record_domain_event(
    *,
    actor,
    event_type: str,
    entity_model: str,
    entity_id=None,
    payload=None,
    request=None,
    enqueue_follow_up: bool = False,
):
    audit_event = log_audit_event(
        actor=actor,
        event_type=event_type,
        entity_model=entity_model,
        entity_id=entity_id,
        payload=payload or {},
        request=request,
    )
    if enqueue_follow_up:
        enqueue_platform_job(
            job_type='domain_event_follow_up',
            payload={
                'event_type': event_type,
                'entity_model': entity_model,
                'entity_id': entity_id,
                'payload': payload or {},
            },
        )
    return audit_event
