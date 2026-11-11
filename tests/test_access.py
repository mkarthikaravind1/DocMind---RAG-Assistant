"""Unit tests for the document-level access rules."""
import pytest

from access import can_access, normalize_roles, role_filter, role_flags, roles_from_str, roles_to_str


def test_admin_is_always_included():
    assert normalize_roles(["employee"]) == ["employee", "admin"]
    assert normalize_roles("manager") == ["manager", "admin"]
    assert normalize_roles([]) == ["admin"]


def test_roles_are_cleaned_and_ordered():
    assert normalize_roles(" Admin , EMPLOYEE,manager ") == ["employee", "manager", "admin"]
    assert roles_to_str(["admin", "manager"]) == "manager,admin"
    assert roles_from_str("manager,admin") == ["manager", "admin"]
    assert roles_from_str(None) == ["admin"]


def test_unknown_roles_are_rejected():
    with pytest.raises(ValueError):
        normalize_roles("manager,boss")


@pytest.mark.parametrize("role, allowed, expected", [
    ("employee", ["employee", "manager", "admin"], True),
    ("employee", ["manager", "admin"], False),
    ("manager", ["manager", "admin"], True),
    ("manager", ["admin"], False),
    ("admin", ["admin"], True),
    ("admin", [], True),              # admins can never be locked out
])
def test_can_access(role, allowed, expected):
    assert can_access(role, allowed) is expected


def test_chunk_flags_and_search_filter():
    assert role_flags(["manager"]) == {"role_employee": False, "role_manager": True, "role_admin": True}
    assert role_filter("employee") == {"role_employee": True}
    with pytest.raises(ValueError):
        role_filter("intruder")
