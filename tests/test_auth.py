"""Registration, login, tokens and admin user management."""
import time

from jose import jwt

from conftest import PASSWORD


def test_protected_routes_need_a_token(env):
    for method, path in [("get", "/files"), ("get", "/auth/me"), ("get", "/conversations"),
                         ("get", "/admin/users"), ("get", "/admin/logs")]:
        assert getattr(env.client, method)(path).status_code == 401, path
    assert env.client.post("/chat", json={"question": "hi"}).status_code == 401
    assert env.client.post("/chat/stream", json={"question": "hi"}).status_code == 401


def test_first_account_is_admin_and_later_ones_are_employees(env):
    assert env.register("First").json()["role"] == "admin"
    assert env.register("Second").json()["role"] == "employee"
    assert env.register("Third").json()["role"] == "employee"


def test_registration_validates_input(env):
    assert env.register("A", email="not-an-email").status_code == 422
    assert env.register("A", password="short").status_code == 422
    assert env.register("   ").status_code == 422
    assert env.client.get("/admin/users").status_code == 401      # nothing was created along the way


def test_duplicate_email_is_rejected_case_insensitively(env):
    assert env.register("Dana", email="dana@example.test").status_code == 200
    r = env.register("Dana Again", email="DANA@Example.Test")
    assert r.status_code == 400 and "already" in r.json()["detail"]


def test_login(env):
    env.register("Dana")
    assert env.client.post("/auth/login", json={"email": "dana@example.test", "password": "wrong-password"}).status_code == 401
    assert env.client.post("/auth/login", json={"email": "nobody@example.test", "password": PASSWORD}).status_code == 401
    r = env.client.post("/auth/login", json={"email": "DANA@EXAMPLE.TEST", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"


def test_me_returns_the_live_profile(env, people):
    me = env.client.get("/auth/me", headers=people["manager"]).json()
    assert me["email"] == "manager@example.test" and me["role"] == "manager"


def test_forged_and_expired_tokens_are_rejected(env, people):
    def token(secret, exp_offset):
        return jwt.encode({"sub": "admin@example.test", "role": "admin", "exp": int(time.time()) + exp_offset},
                          secret, algorithm="HS256")

    for bad in (token("", 3600), token("guessed-secret", 3600),
                token("test-secret-key-not-for-production", -10), "not-a-token"):
        assert env.client.get("/auth/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_role_change_takes_effect_without_a_new_login(env, people):
    # The employee's existing token starts working as a manager the moment an admin promotes them
    assert env.upload(people["employee"], "x.pdf", [["some text here"]]).status_code == 403
    users = env.client.get("/admin/users", headers=people["admin"]).json()
    uid = next(u["id"] for u in users if u["email"] == "employee@example.test")
    assert env.client.patch(f"/admin/users/{uid}/role", headers=people["admin"], json={"role": "manager"}).status_code == 200
    assert env.client.get("/auth/me", headers=people["employee"]).json()["role"] == "manager"
    assert env.upload(people["employee"], "x.pdf", [["some text here"]]).status_code == 200


def test_user_management_is_admin_only_and_validated(env, people):
    for who in ("manager", "employee"):
        assert env.client.get("/admin/users", headers=people[who]).status_code == 403
        assert env.client.patch("/admin/users/1/role", headers=people[who], json={"role": "admin"}).status_code == 403

    users = {u["email"]: u["id"] for u in env.client.get("/admin/users", headers=people["admin"]).json()}
    admin_id, emp_id = users["admin@example.test"], users["employee@example.test"]
    patch = lambda uid, role: env.client.patch(f"/admin/users/{uid}/role", headers=people["admin"], json={"role": role})

    assert patch(admin_id, "employee").status_code == 400        # cannot change own role
    assert patch(emp_id, "superuser").status_code == 400         # unknown role
    assert patch(999999, "manager").status_code == 404           # unknown user
    assert patch(emp_id, "manager").status_code == 200
