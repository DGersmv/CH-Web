def navigation_context(request):
    unread_notifications = 0
    is_leadership_user = False
    show_umnik_chat = False
    can_restart_crm = False
    if getattr(request, 'user', None) and request.user.is_authenticated:
        from accounts.models import Notification
        from accounts.permissions import is_leadership, can_use_umnik_chat, is_platform_owner

        unread_notifications = Notification.objects.filter(user=request.user, is_read=False).count()
        is_leadership_user = is_leadership(request.user)
        show_umnik_chat = can_use_umnik_chat(request.user)
        can_restart_crm = is_platform_owner(request.user)
    path = getattr(request, 'path', '') or ''
    app_shell = path.startswith('/app/')
    return {
        'current_user': request.user,
        'current_path': request.path,
        'unread_notifications': unread_notifications,
        'is_leadership_user': is_leadership_user,
        'show_umnik_chat': show_umnik_chat and not app_shell,
        'can_restart_crm': can_restart_crm,
        'app_shell': app_shell,
        'rooms_ns': 'app' if app_shell else 'rooms',
        'app_base_template': 'rooms/app_base.html' if app_shell else 'base.html',
        'umnik_deal_id': getattr(getattr(request, 'resolver_match', None), 'kwargs', {}).get('pk')
        or getattr(getattr(request, 'resolver_match', None), 'kwargs', {}).get('deal_id')
        or '',
    }
