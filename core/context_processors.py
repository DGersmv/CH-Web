def navigation_context(request):
    unread_notifications = 0
    is_leadership_user = False
    show_umnik_chat = False
    if getattr(request, 'user', None) and request.user.is_authenticated:
        from accounts.models import Notification
        from accounts.permissions import is_leadership, can_use_umnik_chat

        unread_notifications = Notification.objects.filter(user=request.user, is_read=False).count()
        is_leadership_user = is_leadership(request.user)
        show_umnik_chat = can_use_umnik_chat(request.user)
    return {
        'current_user': request.user,
        'current_path': request.path,
        'unread_notifications': unread_notifications,
        'is_leadership_user': is_leadership_user,
        'show_umnik_chat': show_umnik_chat,
        'umnik_deal_id': getattr(getattr(request, 'resolver_match', None), 'kwargs', {}).get('pk')
        or getattr(getattr(request, 'resolver_match', None), 'kwargs', {}).get('deal_id')
        or '',
    }
