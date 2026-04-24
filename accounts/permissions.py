def is_leadership(user) -> bool:
    return getattr(user, 'role', None) in {'head', 'admin'}


def is_file_only_role(user) -> bool:
    return getattr(user, 'role', None) in {'designer', 'production'}


def can_access_file_source(user, source: str) -> bool:
    if source in {'client', 'sales'}:
        return is_leadership(user)
    if source == 'designer':
        return True
    return is_leadership(user)
