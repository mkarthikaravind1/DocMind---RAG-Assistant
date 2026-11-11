"""Uploading, listing, deleting documents and document-level access control."""
import os

from conftest import BOARD, BONUS, HANDBOOK, make_pdf


# ── Who may upload and delete ─────────────────────────────────────────────
def test_only_managers_and_admins_can_upload(env, people):
    assert env.upload(people["employee"], "Handbook.pdf", HANDBOOK).status_code == 403
    assert env.upload(people["manager"], "Handbook.pdf", HANDBOOK).status_code == 200
    assert env.upload(people["admin"], "Bonus.pdf", BONUS).status_code == 200
    assert env.chunk_count() == 3              # 2 handbook pages + 1 memo
    assert sorted(os.listdir(env.upload_dir)) == ["Bonus.pdf", "Handbook.pdf"]


def test_only_admins_can_delete_and_deleting_removes_the_chunks(env, library):
    before = env.chunk_count()
    for who in ("employee", "manager"):
        assert env.client.delete("/delete/Handbook.pdf", headers=library[who]).status_code == 403
    assert env.chunk_count() == before

    assert env.client.delete("/delete/Handbook.pdf", headers=library["admin"]).status_code == 200
    assert env.chunk_count() == before - 2
    assert "Handbook.pdf" not in env.doc_names(library["admin"])
    assert not os.path.exists(os.path.join(env.upload_dir, "Handbook.pdf"))
    assert env.client.delete("/delete/Handbook.pdf", headers=library["admin"]).status_code == 404


# ── Upload validation ─────────────────────────────────────────────────────
def test_reupload_replaces_instead_of_duplicating(env, people):
    first = env.upload(people["admin"], "Handbook.pdf", HANDBOOK).json()
    assert first["status"] == "uploaded and ingested" and first["chunks"] == 2
    second = env.upload(people["admin"], "Handbook.pdf", HANDBOOK).json()
    assert second["status"] == "replaced and re-ingested"
    assert env.chunk_count() == 2
    assert env.doc_names(people["admin"]) == ["Handbook.pdf"]


def test_non_pdf_and_unreadable_files_are_rejected_and_leave_nothing_behind(env, people):
    assert env.upload(people["admin"], "notes.txt", None, content=b"plain text").status_code == 400
    blank = env.upload(people["admin"], "Scanned.pdf", [[]])           # a page with no text
    assert blank.status_code == 422 and "No readable text" in blank.json()["detail"]
    broken = env.upload(people["admin"], "Broken.pdf", None, content=b"this is not a pdf")
    assert broken.status_code == 500

    assert os.listdir(env.upload_dir) == []
    assert env.doc_names(people["admin"]) == []
    assert env.chunk_count() == 0


def test_path_traversal_in_filenames_is_neutralised(env, people):
    outside = os.path.dirname(env.upload_dir)
    for evil, safe in [("../../evil.pdf", "evil.pdf"), ("..\\..\\evil2.pdf", "evil2.pdf"), ("/etc/evil3.pdf", "evil3.pdf")]:
        r = env.upload(people["admin"], evil, BONUS)
        assert r.status_code == 200 and r.json()["filename"] == safe
        assert not os.path.exists(os.path.join(outside, safe))
    assert sorted(os.listdir(env.upload_dir)) == ["evil.pdf", "evil2.pdf", "evil3.pdf"]

    # The delete route must not be usable to remove files outside the folder either
    victim = os.path.join(outside, "victim.pdf")
    open(victim, "wb").write(make_pdf(BONUS))
    for attempt in ("..%5Cvictim.pdf", "..%2Fvictim.pdf", "%2E%2E%5Cvictim.pdf"):
        assert env.client.delete(f"/delete/{attempt}", headers=people["admin"]).status_code in (400, 404)
    assert os.path.exists(victim)
    assert env.client.delete("/delete/..%5C..%5Capp.py", headers=people["admin"]).status_code == 400


# ── Audiences ─────────────────────────────────────────────────────────────
def test_upload_audience_rules(env, people):
    default = env.upload(people["admin"], "Open.pdf", HANDBOOK).json()
    assert default["allowed_roles"] == ["employee", "manager", "admin"]

    kept = env.upload(people["admin"], "EmpOnly.pdf", BONUS, "employee").json()
    assert kept["allowed_roles"] == ["employee", "admin"]              # admins are never locked out

    locked_out = env.upload(people["manager"], "Mine.pdf", BONUS, "admin")
    assert locked_out.status_code == 400                               # a manager cannot exclude managers
    assert env.upload(people["manager"], "Mine.pdf", BONUS, "manager,boss").status_code == 400
    assert "Mine.pdf" not in os.listdir(env.upload_dir)


def test_manager_cannot_overwrite_an_admins_only_document(env, library):
    r = env.upload(library["manager"], "Board.pdf", BONUS, "manager,admin")
    assert r.status_code == 409
    docs = {d["filename"]: d for d in env.client.get("/files", headers=library["admin"]).json()["documents"]}
    assert docs["Board.pdf"]["allowed_roles"] == ["admin"]
    flags = env.chroma.get_collection("rag_docs").get(where={"filename": "Board.pdf"}, include=["documents", "metadatas"])
    assert "Kestrel" in flags["documents"][0] and flags["metadatas"][0]["role_manager"] is False


def test_each_role_sees_only_its_documents(env, library):
    assert env.doc_names(library["employee"]) == ["Handbook.pdf"]
    assert env.doc_names(library["manager"]) == ["Bonus.pdf", "Handbook.pdf"]
    assert env.doc_names(library["admin"]) == ["Board.pdf", "Bonus.pdf", "Handbook.pdf"]


def test_chunks_are_tagged_with_their_audience(env, library):
    data = env.chroma.get_collection("rag_docs").get(include=["metadatas"])
    tags = {m["filename"]: (m["role_employee"], m["role_manager"], m["role_admin"]) for m in data["metadatas"]}
    assert tags == {
        "Handbook.pdf": (True, True, True),
        "Bonus.pdf": (False, True, True),
        "Board.pdf": (False, False, True),
    }


def test_admin_can_change_a_documents_audience(env, library):
    url = "/documents/Bonus.pdf/access"
    assert env.client.patch(url, headers=library["manager"], json={"allowed_roles": ["employee"]}).status_code == 403

    opened = env.client.patch(url, headers=library["admin"], json={"allowed_roles": ["employee", "manager"]})
    assert opened.status_code == 200 and opened.json()["allowed_roles"] == ["employee", "manager", "admin"]
    assert "Bonus.pdf" in env.doc_names(library["employee"])

    closed = env.client.patch(url, headers=library["admin"], json={"allowed_roles": []})
    assert closed.json()["allowed_roles"] == ["admin"]
    assert "Bonus.pdf" not in env.doc_names(library["manager"])
    meta = env.chroma.get_collection("rag_docs").get(where={"filename": "Bonus.pdf"}, include=["metadatas"])["metadatas"][0]
    assert (meta["role_employee"], meta["role_manager"], meta["role_admin"]) == (False, False, True)
    assert meta["filename"] == "Bonus.pdf" and "page" in meta           # other metadata is preserved

    assert env.client.patch(url, headers=library["admin"], json={"allowed_roles": ["wizard"]}).status_code == 400
    assert env.client.patch("/documents/Nope.pdf/access", headers=library["admin"], json={"allowed_roles": ["admin"]}).status_code == 404


def test_reupload_with_a_narrower_audience_replaces_the_old_tags(env, library):
    assert env.upload(library["manager"], "Handbook.pdf", HANDBOOK, "manager,admin").status_code == 200
    assert env.doc_names(library["employee"]) == []
    data = env.chroma.get_collection("rag_docs").get(where={"filename": "Handbook.pdf"}, include=["metadatas"])
    assert len(data["ids"]) == 2 and all(m["role_employee"] is False for m in data["metadatas"])


def test_files_without_an_access_record_are_flagged_for_admins_only(env, library):
    open(os.path.join(env.upload_dir, "Legacy.pdf"), "wb").write(make_pdf(BOARD))

    admin_view = env.client.get("/files", headers=library["admin"]).json()
    legacy = [d for d in admin_view["documents"] if d["filename"] == "Legacy.pdf"]
    assert len(legacy) == 1 and legacy[0]["indexed"] is False
    assert "Legacy.pdf" not in admin_view["docs"]
    for who in ("manager", "employee"):
        assert "Legacy.pdf" not in env.doc_names(library[who])
