def is_leadership(user) -> bool:
    return getattr(user, 'role', None) in {'head', 'admin'}


def is_admin(user) -> bool:
    if not user:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) == 'admin'


def can_use_umnik_chat(user) -> bool:
    return bool(user and getattr(user, 'is_authenticated', False) and getattr(user, 'is_active', True))


def is_file_only_role(user) -> bool:
    return getattr(user, 'role', None) in {'designer', 'production'}


def can_edit_deals(user) -> bool:
    if not user or not getattr(user, 'is_active', False):
        return False
    return not is_file_only_role(user)


def can_delete_deals(user) -> bool:
    return is_admin(user)


def umnik_capabilities(user) -> dict:
    admin = is_admin(user)
    edit = can_edit_deals(user)
    return {
        'username': getattr(user, 'username', '') or '',
        'role': getattr(user, 'role', '') or '',
        'is_admin': admin,
        'can_view': True,
        'can_edit': edit,
        'can_delete': admin,
        'can_copy_files': edit or admin,
    }


def can_access_file_source(user, source: str) -> bool:
    if source in {'client', 'sales'}:
        return is_leadership(user)
    if source == 'designer':
        return True
    return is_leadership(user)
