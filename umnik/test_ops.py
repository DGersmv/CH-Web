from ops import actor_may_restart


def test_actor_may_restart_only_platform_owner_login():
    assert actor_may_restart("superadmin")
    assert not actor_may_restart("admin")
    assert not actor_may_restart("boss")
    assert not actor_may_restart("")
    assert actor_may_restart("boss", {"is_superuser": True})
    assert actor_may_restart("x", {"can_restart_crm": True})
    assert not actor_may_restart("role-admin", {"is_admin": True, "can_delete": True})
