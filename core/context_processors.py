def navigation_context(request):
    unread_notifications = 0
    is_leadership_user = False
    if getattr(request, 'user', None) and request.user.is_authenticated:
        from accounts.models import Notification
        from accounts.permissions import is_leadership

        unread_notifications = Notification.objects.filter(user=request.user, is_read=False).count()
        is_leadership_user = is_leadership(request.user)
    return {
        'current_user': request.user,
        'current_path': request.path,
        'unread_notifications': unread_notifications,
        'is_leadership_user': is_leadership_user,
    }
