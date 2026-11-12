"""Audit trail: role changes, uploads, deletes, access changes, registrations, sign-ins and denials."""
import pytest

import audit
from conftest import BONUS, HANDBOOK, PASSWORD, Q_LEAVE, make_pdf

EVENT_KEYS = {"id", "timestamp", "actor_email", "actor_role", "action", "target", "details", "outcome"}
ADMIN, MANAGER, EMPLOYEE = "admin@example.test", "manager@example.test", "employee@example.test"


def events(env, admin, **params):
    r = env.client.get("/admin/audit", headers=admin, params=params)
    assert r.status_code == 200, r.text
    return r.json()["events"]


def last(env, admin, action):
    """The newest event of one kind."""
    found = events(env, admin, action=action, limit=1)
    assert found, f"no {action} event"
    return found[0]


def summary(event):
    return (event["action"], event["actor_email"], event["target"], event["outcome"])


# ── Accounts and sign-ins ─────────────────────────────────────────────────
def test_registrations_are_recorded_and_the_first_admin_is_marked(env, people):
    registered = events(env, people["admin"], action="user_register")
    assert [(e["target"], e["details"]) for e in reversed(registered)] == [
        (ADMIN,    {"role": "admin", "first_admin": True}),
        (MANAGER,  {"role": "employee", "first_admin": False}),     # promoted afterwards
        (EMPLOYEE, {"role": "employee", "first_admin": False}),
    ]
    assert all(e["outcome"] == "success" and set(e) == EVENT_KEYS for e in registered)


def test_a_rejected_registration_leaves_no_event(env, people):
    before = len(events(env, people["admin"], action="user_register"))
    assert env.register("Employee").status_code == 400                # email already taken
    assert env.register("Short", password="abc").status_code == 422   # invalid input
    assert len(events(env, people["admin"], action="user_register")) == before


def test_sign_ins_and_failed_sign_ins_are_recorded(env, people):
    admin = people["admin"]
    env.login("Employee")
    event = last(env, admin, "login")
    assert summary(event) == ("login", EMPLOYEE, EMPLOYEE, "success") and event["actor_role"] == "employee"

    wrong = env.client.post("/auth/login", json={"email": EMPLOYEE, "password": "not-the-password"})
    unknown = env.client.post("/auth/login", json={"email": "Ghost@Example.test", "password": PASSWORD})
    # The response gives nothing away about which of the two it was...
    assert wrong.status_code == unknown.status_code == 401 and wrong.json() == unknown.json()

    # ...but the audit trail knows
    failed = events(env, admin, action="login_failed")
    assert [(e["target"], e["details"]["reason"], e["actor_email"], e["outcome"]) for e in failed] == [
        ("ghost@example.test", "unknown_account", None, "failed"),
        (EMPLOYEE, "wrong_password", None, "failed"),
    ]


def test_passwords_and_tokens_never_reach_the_audit_trail(env, people):
    env.client.post("/auth/login", json={"email": EMPLOYEE, "password": "Sup3r-secret-guess!"})
    token = env.login("Employee")["Authorization"].split()[1]
    text = env.client.get("/admin/audit", headers=people["admin"], params={"limit": 200}).text
    for secret in (PASSWORD, "Sup3r-secret-guess!", token, "hashed_password", "$2b$"):
        assert secret not in text


# ── Role changes ──────────────────────────────────────────────────────────
def test_role_changes_record_who_whom_and_old_and_new_role(env, people):
    admin = people["admin"]
    promoted = last(env, admin, "role_change")                          # done by the `people` fixture
    assert summary(promoted) == ("role_change", ADMIN, MANAGER, "success")
    assert promoted["details"] == {"from": "employee", "to": "manager"} and promoted["actor_role"] == "admin"

    users = env.client.get("/admin/users", headers=admin).json()
    uid = next(u["id"] for u in users if u["email"] == MANAGER)
    env.client.patch(f"/admin/users/{uid}/role", headers=admin, json={"role": "employee"})
    assert last(env, admin, "role_change")["details"] == {"from": "manager", "to": "employee"}


def test_refused_role_changes_are_not_recorded_as_changes(env, people):
    admin = people["admin"]
    users = env.client.get("/admin/users", headers=admin).json()
    own = next(u["id"] for u in users if u["email"] == ADMIN)
    before = len(events(env, admin, action="role_change"))
    assert env.client.patch(f"/admin/users/{own}/role", headers=admin, json={"role": "employee"}).status_code == 400
    assert env.client.patch("/admin/users/9999/role", headers=admin, json={"role": "manager"}).status_code == 404
    assert env.client.patch(f"/admin/users/{own}/role", headers=admin, json={"role": "wizard"}).status_code == 400
    assert len(events(env, admin, action="role_change")) == before


def test_the_role_change_and_its_audit_row_are_saved_together(env, people, monkeypatch):
    """If the audit row cannot be written, the role must not change either."""
    admin = people["admin"]
    uid = next(u["id"] for u in env.client.get("/admin/users", headers=admin).json() if u["email"] == EMPLOYEE)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated audit failure")
    monkeypatch.setattr(audit, "AuditLog", boom)
    with pytest.raises(RuntimeError):
        env.client.patch(f"/admin/users/{uid}/role", headers=admin, json={"role": "manager"})
    monkeypatch.undo()

    roles = {u["email"]: u["role"] for u in env.client.get("/admin/users", headers=people["admin"]).json()}
    assert roles[EMPLOYEE] == "employee"


# ── Documents ─────────────────────────────────────────────────────────────
def test_uploads_record_audience_chunks_and_replacement(env, people):
    admin = people["admin"]
    assert env.upload(people["manager"], "Bonus.pdf", BONUS, "manager,admin").status_code == 200
    event = last(env, admin, "document_upload")
    assert summary(event) == ("document_upload", MANAGER, "Bonus.pdf", "success")
    assert event["details"] == {
        "allowed_roles": ["manager", "admin"], "chunks": 1, "replaced": False, "previous_roles": None,
    }

    assert env.upload(admin, "Bonus.pdf", BONUS, "admin").status_code == 200       # narrower re-upload
    event = last(env, admin, "document_upload")
    assert event["actor_email"] == ADMIN
    assert event["details"] == {
        "allowed_roles": ["admin"], "chunks": 1, "replaced": True, "previous_roles": ["manager", "admin"],
    }


def test_failed_and_refused_uploads_are_recorded_with_a_reason(env, people):
    admin, manager = people["admin"], people["manager"]
    assert env.upload(admin, "Empty.pdf", [[]]).status_code == 422                 # no readable text
    event = last(env, admin, "document_upload")
    assert summary(event) == ("document_upload", ADMIN, "Empty.pdf", "failed")
    assert event["details"] == {"reason": "no readable text"}

    env.upload(admin, "Board.pdf", HANDBOOK, "admin")
    assert env.upload(manager, "Board.pdf", BONUS, "manager,admin").status_code == 409   # overwrite attempt
    event = last(env, admin, "document_upload")
    assert summary(event) == ("document_upload", MANAGER, "Board.pdf", "denied")


def test_deletes_record_the_document_and_the_audience_it_had(env, library):
    admin = library["admin"]
    assert env.client.delete("/delete/Bonus.pdf", headers=admin).status_code == 200
    event = last(env, admin, "document_delete")
    assert summary(event) == ("document_delete", ADMIN, "Bonus.pdf", "success")
    assert event["details"] == {"allowed_roles": ["manager", "admin"]}

    before = len(events(env, admin, action="document_delete"))
    assert env.client.delete("/delete/Nothing.pdf", headers=admin).status_code == 404
    assert len(events(env, admin, action="document_delete")) == before


def test_access_changes_record_the_old_and_new_audience(env, library):
    admin = library["admin"]
    r = env.client.patch("/documents/Bonus.pdf/access", headers=admin, json={"allowed_roles": ["admin"]})
    assert r.status_code == 200
    event = last(env, admin, "access_change")
    assert summary(event) == ("access_change", ADMIN, "Bonus.pdf", "success")
    assert event["details"] == {"from": ["manager", "admin"], "to": ["admin"]}

    before = len(events(env, admin, action="access_change"))
    assert env.client.patch("/documents/Nope.pdf/access", headers=admin, json={"allowed_roles": ["admin"]}).status_code == 404
    assert env.client.patch("/documents/Bonus.pdf/access", headers=admin, json={"allowed_roles": ["wizard"]}).status_code == 400
    assert len(events(env, admin, action="access_change")) == before


def test_a_vector_store_failure_is_recorded_and_nothing_changes(env, library, monkeypatch):
    import app as app_module
    admin = library["admin"]

    def boom(*args, **kwargs):
        raise RuntimeError("simulated vector store outage")
    monkeypatch.setattr(app_module, "set_document_roles", boom)
    monkeypatch.setattr(app_module, "delete_document_chunks", boom)

    assert env.client.patch("/documents/Bonus.pdf/access", headers=admin, json={"allowed_roles": ["admin"]}).status_code == 503
    assert env.client.delete("/delete/Bonus.pdf", headers=admin).status_code == 503
    failed = events(env, admin, outcome="failed")
    assert [summary(e) for e in failed[:2]] == [
        ("document_delete", ADMIN, "Bonus.pdf", "failed"),
        ("access_change", ADMIN, "Bonus.pdf", "failed"),
    ]
    assert "Bonus.pdf" in env.doc_names(library["manager"])           # still there, still readable by managers


# ── Denials ───────────────────────────────────────────────────────────────
def test_permission_denied_attempts_are_recorded(env, library):
    admin, emp = library["admin"], library["employee"]
    assert env.client.get("/admin/users", headers=emp).status_code == 403
    assert env.client.delete("/delete/Handbook.pdf", headers=library["manager"]).status_code == 403
    assert env.upload(emp, "Mine.pdf", BONUS).status_code == 403
    assert env.client.get("/admin/audit", headers=emp).status_code == 403

    denied = events(env, admin, action="access_denied")
    assert [(e["actor_email"], e["actor_role"], e["target"], e["outcome"]) for e in denied] == [
        (EMPLOYEE, "employee", "GET /admin/audit", "denied"),
        (EMPLOYEE, "employee", "POST /upload", "denied"),
        (MANAGER, "manager", "DELETE /delete/Handbook.pdf", "denied"),
        (EMPLOYEE, "employee", "GET /admin/users", "denied"),
    ]
    assert denied[2]["details"] == {"required_roles": ["admin"]}
    assert denied[1]["details"] == {"required_roles": ["admin", "manager"]}


def test_requests_without_a_valid_token_are_not_audited(env, people):
    before = len(events(env, people["admin"], limit=200))
    assert env.client.get("/admin/users").status_code in (401, 403)
    assert env.client.get("/admin/users", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert len(events(env, people["admin"], limit=200)) == before


def test_ordinary_activity_is_not_in_the_audit_trail(env, library):
    """Chats have their own query log; reading lists changes nothing."""
    admin, emp = library["admin"], library["employee"]
    before = len(events(env, admin, limit=200))
    env.ask(emp, Q_LEAVE)
    env.client.get("/files", headers=emp)
    env.client.get("/admin/logs", headers=admin)
    env.client.get("/admin/users", headers=admin)
    assert len(events(env, admin, limit=200)) == before


# ── Reading the trail ─────────────────────────────────────────────────────
def test_the_audit_trail_is_admin_only(env, people):
    for who in ("manager", "employee"):
        assert env.client.get("/admin/audit", headers=people[who]).status_code == 403
    assert env.client.get("/admin/audit").status_code in (401, 403)


def test_the_audit_trail_cannot_be_changed_through_the_api(env, people):
    admin = people["admin"]
    first = events(env, admin, limit=200)
    event_id = first[0]["id"]
    for method in ("post", "put", "patch", "delete"):
        for url in ("/admin/audit", f"/admin/audit/{event_id}"):
            r = getattr(env.client, method)(url, headers=admin)
            assert r.status_code in (404, 405), (method, url, r.status_code)
    assert [e["id"] for e in events(env, admin, limit=200)][-len(first):] == [e["id"] for e in first]


def test_events_are_newest_first_and_can_be_filtered(env, library):
    admin = library["admin"]
    everything = events(env, admin, limit=200)
    assert [e["id"] for e in everything] == sorted((e["id"] for e in everything), reverse=True)
    assert all(e["timestamp"].endswith("+00:00") for e in everything)

    assert {e["action"] for e in events(env, admin, action="document_upload")} == {"document_upload"}
    by_manager = events(env, admin, actor="Manager@Example.test ")       # case and spaces are forgiven
    assert by_manager and {e["actor_email"] for e in by_manager} == {MANAGER}
    assert {e["action"] for e in by_manager} == {"user_register", "login", "document_upload"}
    assert events(env, admin, actor="nobody@example.test") == []
    assert events(env, admin, outcome="denied") == []

    for bad in ({"action": "explode"}, {"outcome": "maybe"}):
        assert env.client.get("/admin/audit", headers=admin, params=bad).status_code == 400
    for bad in ({"limit": 0}, {"limit": 201}, {"before": 0}):
        assert env.client.get("/admin/audit", headers=admin, params=bad).status_code == 422


def test_paging_walks_through_every_event_exactly_once(env, library):
    admin = library["admin"]
    everything = [e["id"] for e in events(env, admin, limit=200)]
    assert len(everything) > 6

    seen, before = [], None
    for _ in range(50):
        params = {"limit": 4, **({"before": before} if before else {})}
        page = env.client.get("/admin/audit", headers=admin, params=params).json()
        assert 0 < len(page["events"]) <= 4
        seen += [e["id"] for e in page["events"]]
        before = page["next_before"]
        if before is None:
            break
    assert seen == everything
    assert set(env.client.get("/admin/audit", headers=admin).json()["actions"]) == set(audit.ACTIONS)


# ── PII ───────────────────────────────────────────────────────────────────
def test_pii_in_a_filename_is_redacted_but_account_emails_stay_readable(env, people):
    admin = people["admin"]
    name = "Card 4111 1111 1111 1111 for 9876543210.pdf"
    assert env.client.post("/upload", headers=admin, data={"allowed_roles": "admin"},
                           files={"file": (name, make_pdf(BONUS), "application/pdf")}).status_code == 200
    event = last(env, admin, "document_upload")
    assert "4111" not in event["target"] and "9876543210" not in event["target"]
    assert event["target"].count("[REDACTED]") == 2 and event["target"].endswith(".pdf")
    assert event["actor_email"] == ADMIN                      # who did it is the point of an audit trail


def test_unknown_actions_cannot_be_recorded():
    with pytest.raises(ValueError):
        audit.add(None, "made_up_action")
