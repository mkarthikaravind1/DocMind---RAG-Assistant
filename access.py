# access.py
# Document-level access control: which roles may see and query a document.
#
# Each document stores a list of allowed roles. The same list is written onto
# every chunk in the vector store as one boolean flag per role
# (role_employee / role_manager / role_admin), so retrieval can filter on the
# asker's role *inside* the vector search. Restricted text never reaches the LLM.

ROLES = ("employee", "manager", "admin")
DEFAULT_ROLES = list(ROLES)   # visible to everyone


def normalize_roles(roles) -> list[str]:
    """
    Validate and tidy a role list. Accepts a list or a comma-separated string.
    Admins always keep access, so a document can never be locked away from them.
    Raises ValueError on an unknown role.
    """
    if isinstance(roles, str):
        roles = roles.split(",")
    cleaned = {str(r).strip().lower() for r in roles if str(r).strip()}
    unknown = cleaned - set(ROLES)
    if unknown:
        raise ValueError(f"Unknown role(s): {', '.join(sorted(unknown))}")
    cleaned.add("admin")
    return [r for r in ROLES if r in cleaned]   # stable order


def roles_to_str(roles) -> str:
    return ",".join(normalize_roles(roles))


def roles_from_str(value) -> list[str]:
    return normalize_roles(value or "admin")


def can_access(user_role: str, allowed_roles) -> bool:
    return user_role == "admin" or user_role in allowed_roles


def role_flags(roles) -> dict:
    """Chunk metadata flags, e.g. {'role_employee': False, 'role_manager': True, 'role_admin': True}."""
    allowed = normalize_roles(roles)
    return {f"role_{r}": (r in allowed) for r in ROLES}


def role_filter(user_role: str) -> dict:
    """Vector-store filter that only matches chunks this role may read."""
    if user_role not in ROLES:
        raise ValueError(f"Unknown role: {user_role}")
    return {f"role_{user_role}": True}
