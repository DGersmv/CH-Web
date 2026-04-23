def navigation_context(request):
    return {
        'current_user': request.user,
        'current_path': request.path,
    }
