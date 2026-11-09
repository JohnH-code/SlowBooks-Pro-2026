"""John's build: QuickBooks' documents attached to a company imported
without them, from the Attach folder on this computer and an attachment
map; run again, nothing is attached twice."""

from app.models.attachments import Attachment
from app.models.transactions import Transaction
from app.services import qbd_import


def test_documents_go_onto_the_imported_transaction(
    client, seed_accounts, tmp_path, TestSession
):
    v = client.post("/api/vendors", json={"name": "Oakville Club"}).json()["id"]
    r = client.post(
        "/api/expenses",
        json={
            "date": "2026-10-31",
            "vendor_id": v,
            "paid_from_account_id": seed_accounts["1000"].id,
            "amount": 50.0,
            "lines": [{"account_id": seed_accounts["6400"].id, "amount": 50.0}],
        },
    )
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    with TestSession() as s:
        t = s.query(Transaction).filter(Transaction.source_type == "expense").one()
        t.reference = "QB #8391"
        s.commit()
    txn = tmp_path / "Attach" / "Alderella Holdings Inc" / "Txn"
    (txn / "8000AC98-1794235683").mkdir(parents=True)
    (txn / "8000AC98-1794235683" / "statement.pdf").write_bytes(b"%PDF club")
    (txn / "8000AC98-1794235683" / "photo.HEIC").write_bytes(b"heic")
    (txn / "8000AC98-1794235683" / "Thumbs.db").write_bytes(b"x")
    amap = "Trans #,Folder\n8391,8000AC98-1794235683\n9999,8000FFFF-1\n7,80000001-1\n"
    url = "/api/migration/qbd/attach-folder"
    body = {
        "folder": str(tmp_path / "Attach" / "Alderella Holdings Inc"),
        "map_csv": amap,
    }
    got = client.post(url, json={**body, "apply": False}).json()
    assert (got["folders"], got["attached"]) == (1, 1)
    assert got["unsupported"] == ["8000AC98-1794235683/photo.HEIC"]
    assert got["not_found"] == ["80000001-1", "8000FFFF-1"]
    with TestSession() as s:
        assert s.query(Attachment).count() == 0  # a check writes nothing
    got = client.post(url, json={**body, "apply": True}).json()
    assert got["attached"] == 1
    with TestSession() as s:
        (a,) = s.query(Attachment).all()
        assert (a.entity_type, a.filename) == ("expense", "statement.pdf")
        assert a.entity_id == eid or a.entity_id == t.id
    again = client.post(url, json={**body, "apply": True}).json()
    assert (again["attached"], again["already"]) == (0, 1)


def test_a_folder_without_txn_is_refused(client, tmp_path):
    r = client.post(
        "/api/migration/qbd/attach-folder",
        json={"folder": str(tmp_path), "map_csv": "Trans #,Folder\n1,a\n"},
    )
    assert r.status_code == 422
    assert qbd_import.parse_attach_map("x,y\n")[1]
