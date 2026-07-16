from django.utils import timezone

from deals.models import DealClientPortalOtp, DealClientPortalSession


def cleanup_expired_portal_access(_job):
    otp_deleted, _ = DealClientPortalOtp.objects.filter(
        expires_at__lt=timezone.now(),
    ).delete()
    session_deleted, _ = DealClientPortalSession.objects.filter(
        expires_at__lt=timezone.now(),
    ).delete()
    return {
        'deleted_otps': otp_deleted,
        'deleted_sessions': session_deleted,
    }


JOB_HANDLERS = {
    'cleanup_expired_portal_access': cleanup_expired_portal_access,
}
