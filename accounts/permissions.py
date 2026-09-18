ASSIGNABLE_ROLES = ('manager', 'designer', 'production', 'admin', 'head')
OWNER_ROLE = 'superadmin'
LEADERSHIP_ROLES = {'head', 'admin', 'superadmin'}


def assignable_role_choices():
    from accounts.models import User

    return [choice for choice in User.Role.choices if choice[0] != User.Role.SUPERADMIN]


def staff_users_qs(queryset=None):
    from django.contrib.auth import get_user_model

    qs = queryset if queryset is not None else get_user_model().objects.all()
    return qs.exclude(role=OWNER_ROLE)


def is_leadership(user) -> bool:
    return getattr(user, 'role', None) in LEADERSHIP_ROLES


def is_platform_owner(user) -> bool:
    """Владелец системы: роль superadmin или Django is_superuser.

    Роль admin и логин admin сюда не входят — admin можно выдать сотруднику.
    """
    if not user or not getattr(user, 'is_active', False):
        return False
    if not getattr(user, 'is_authenticated', True):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) == OWNER_ROLE


def is_admin(user) -> bool:
    if not user:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'role', None) in {'admin', OWNER_ROLE}


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


def can_attach_design_files(user) -> bool:
    """Класть PDF в разделы проектирования можно всем активным сотрудникам, включая проектировщика."""
    return bool(user and getattr(user, 'is_active', False) and getattr(user, 'is_authenticated', True))


def umnik_capabilities(user) -> dict:
    admin = is_admin(user)
    edit = can_edit_deals(user)
    owner = is_platform_owner(user)
    attach = can_attach_design_files(user)
    return {
        'username': getattr(user, 'username', '') or '',
        'role': getattr(user, 'role', '') or '',
        'is_admin': admin,
        'is_superuser': bool(getattr(user, 'is_superuser', False)),
        'is_platform_owner': owner,
        'can_view': True,
        'can_edit': edit,
        'can_delete': admin,
        'can_copy_files': attach,
        'can_attach_design_files': attach,
        'can_edit_code': owner,
        'can_restart_crm': owner,
    }


def can_access_file_source(user, source: str) -> bool:
    if source in {'client', 'sales'}:
        return is_leadership(user)
    if source == 'designer':
        return True
    return is_leadership(user)
