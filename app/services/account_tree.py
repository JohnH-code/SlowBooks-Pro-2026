# ============================================================================
# Sub-accounts on the financial statements, as QuickBooks shows them:
#
#   Auto                              (header)
#       Fuel                 1,200.00
#       Insurance            2,400.00
#       Auto - Other           150.00 (what was posted to Auto itself)
#   Total Auto               3,750.00
#
# A report's rows are one per account with postings; this orders them under
# their parents, adds the parents that have none of their own, and gives
# each parent its "- Other" and "Total" lines. The section totals don't
# change: a header and a total are display lines, not more money.
# ============================================================================

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.accounts import Account


def account_tree(
    db: Session, items: list[dict], accounts: dict | None = None, sort: str = "number"
) -> list[dict]:
    """Display lines for one section of a report.

    Each is {kind, label, depth, account_id, amount, prior_amount}: kind is
    "account" (an account's own figure), "header" (a parent's name, no
    figure), "other" (a parent's own postings beside its sub-accounts) or
    "total" (a parent with its sub-accounts). Rows with no account (Net
    Income on the balance sheet) come last, as they were."""
    if accounts is None:
        accounts = {a.id: a for a in db.query(Account).all()}
    by_id = {i["account_id"]: i for i in items if i.get("account_id") in accounts}
    loose = [i for i in items if i.get("account_id") not in accounts]

    needed: set[int] = set()
    for aid in by_id:
        cur = accounts.get(aid)
        guard = 0
        while cur is not None and cur.id not in needed and guard < 50:
            needed.add(cur.id)
            cur = accounts.get(cur.parent_id) if cur.parent_id else None
            guard += 1
    kids: dict[int | None, list[int]] = {}
    for aid in needed:
        parent = accounts[aid].parent_id
        kids.setdefault(parent if parent in needed else None, []).append(aid)

    def order(ids):
        # the report's order (#326): by number then name, or by name
        if sort == "name":
            return sorted(
                ids,
                key=lambda i: (
                    accounts[i].name.lower(),
                    accounts[i].account_number or "",
                ),
            )
        return sorted(
            ids,
            key=lambda i: (
                (accounts[i].account_number or "~"),
                accounts[i].name.lower(),
            ),
        )

    def words(acct):
        # the number first, as the statements' rows read (W-8)
        return (
            f"{acct.account_number} - {acct.name}" if acct.account_number else acct.name
        )

    out: list[dict] = []

    def emit(aid: int, depth: int) -> tuple[float, float]:
        acct = accounts[aid]
        item = by_id.get(aid) or {}
        own = float(item.get("amount") or 0)
        own_prior = float(item.get("prior_amount") or 0)
        children = order(kids.get(aid, []))
        if not children:
            out.append(
                {
                    **item,
                    "kind": "account",
                    "label": words(acct),
                    "depth": depth,
                    "account_id": aid,
                    "account_name": item.get("account_name", acct.name),
                    "amount": own,
                    "prior_amount": own_prior,
                }
            )
            return own, own_prior
        out.append(
            {
                "kind": "header",
                "label": words(acct),
                "depth": depth,
                "account_id": aid,
                "account_name": acct.name,
                "amount": None,
                "prior_amount": None,
            }
        )
        total, total_prior = own, own_prior
        for c in children:
            a, p = emit(c, depth + 1)
            total += a
            total_prior += p
        if own or own_prior:
            out.append(
                {
                    "kind": "other",
                    "label": f"{acct.name} - Other",
                    "depth": depth + 1,
                    "account_id": aid,
                    "account_name": acct.name,
                    "amount": own,
                    "prior_amount": own_prior,
                }
            )
        out.append(
            {
                "kind": "total",
                "label": f"Total {acct.name}",
                "depth": depth,
                "account_id": None,
                "account_name": f"Total {acct.name}",
                "amount": round(total, 2),
                "prior_amount": round(total_prior, 2),
            }
        )
        return total, total_prior

    for root in order(kids.get(None, [])):
        emit(root, 0)
    for i in loose:
        out.append(
            {
                **i,
                "kind": "account",
                "label": i.get("account_label") or i.get("account_name", ""),
                "depth": 0,
                "amount": float(i.get("amount") or 0),
                "prior_amount": float(i.get("prior_amount") or 0),
            }
        )
    return out


def add_trees(db: Session, data: dict, keys) -> dict:
    """data["tree"][key] = account_tree(data[key]) for each section, in the
    report's own order (data["sort"])."""
    accounts = {a.id: a for a in db.query(Account).all()}
    sort = data.get("sort") if data.get("sort") in ("number", "name") else "number"
    data["tree"] = {
        k: account_tree(db, data.get(k) or [], accounts, sort) for k in keys
    }
    return data
