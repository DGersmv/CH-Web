def navigation_context(request):
    unread_notifications = 0
    if getattr(request, 'user', None) and request.user.is_authenticated:
        from accounts.models import Notification

        unread_notifications = Notification.objects.filter(user=request.user, is_read=False).count()
    return {
        'current_user': request.user,
        'current_path': request.path,
        'unread_notifications': unread_notifications,
    }
