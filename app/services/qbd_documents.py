# ============================================================================
# QuickBooks Desktop import — invoices, payments, bills and bill payments as
# documents (services/qbd_import.py brings everything else).
#
# The Journal report carries each invoice with its customer, number, terms,
# due date and lines (item, quantity, price, HST), each customer payment, each
# bill and each bill payment — but not which payment paid which invoice. That
# comes from its Open Balance column: what QuickBooks still shows open on each
# invoice and bill (and unapplied on each payment). Each document is paid up
# to exactly that, from its customer's (vendor's) payments oldest first, so
# every open balance, the A/R and A/P aging and every customer's and vendor's
# balance equal QuickBooks'.
#
# The postings are QuickBooks' own lines, unchanged: a document only says
# what they were. The books stay what the Balance Sheet and P&L verified.
#
# A general journal entry that posts to receivables or payables (QuickBooks'
# sales tax filing makes one, owed by or to the Receiver General) stays a
# journal entry, with an invoice, payment, bill or bill payment beside it for
# the receivable or payable it made, so the customer's or vendor's balance
# reads right.
# ============================================================================

import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

ZERO = Decimal("0")
CENT = Decimal("0.01")

INVOICE, PAYMENT, BILL, BILL_PAYMENT = "invoice", "payment", "bill", "bill_payment"
DOC_KINDS = (INVOICE, PAYMENT, BILL, BILL_PAYMENT)


def _q(v) -> Decimal:
    return Decimal(str(v)).quantize(CENT)


def _num(s: str):
    s = (s or "").replace(",", "").strip()
    if not s or s.endswith("%"):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _date(s: str):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime((s or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def _rate(price: str):
    """'13.00%' → 0.13 (the fraction Slowbooks keeps), else None."""
    m = re.fullmatch(r"\s*(-?[\d.]+)\s*%\s*", price or "")
    return (Decimal(m.group(1)) / 100) if m else None


def _lines(t):
    return [l for l in t["lines"] if l["debit"] or l["credit"]]


def classify(t: dict, qtype: dict) -> str | None:
    """invoice, payment, bill or bill payment — when the transaction has the
    shape that document posts in QuickBooks — else None."""
    ttype = (t["type"] or "").strip().lower()
    lines = _lines(t)
    if len(lines) < 2:
        return None
    head = lines[0]
    ar = [l for l in lines if qtype.get(l["account"]) == "AR"]
    ap = [l for l in lines if qtype.get(l["account"]) == "AP"]
    if ttype == "invoice" and len(ar) == 1 and ar[0] is head and head["debit"] > head["credit"] and not ap:
        return INVOICE
    if ttype == "payment" and len(ar) == 1 and ar[0] is not head and ar[0]["credit"] > ar[0]["debit"] and not ap:
        if qtype.get(head["account"]) not in ("AR", "AP") and head["debit"] > head["credit"]:
            return PAYMENT
    if ttype == "bill" and len(ap) == 1 and ap[0] is head and head["credit"] > head["debit"] and not ar:
        return BILL
    if ttype.startswith("bill pmt") and len(ap) == 1 and ap[0] is not head and ap[0]["debit"] > ap[0]["credit"] and not ar:
        if qtype.get(head["account"]) in ("BANK", "CCARD") and head["credit"] > head["debit"]:
            return BILL_PAYMENT
    return None


def _who(t, line):
    return (line["name"] or t["name"] or "").strip()


def plan(txns: list[dict], qtype: dict) -> dict:
    """What each transaction becomes and how the documents pay each other.

    Returns {"kind": {trans: kind}, "side": {trans: [(kind, line index, who,
    amount)]} for journal entries that touch A/R or A/P, "alloc": {(payment
    trans or side key, invoice trans or side key): amount}, "open": {key:
    open amount}, "notes": [...]}. Keys are (trans, line index)."""
    kind: dict[str, str] = {}
    side: dict[str, list] = defaultdict(list)
    receivables = defaultdict(list)  # who → [(date, key, capacity)]
    credits = defaultdict(list)  # who → [(date, key, available)]
    payables = defaultdict(list)
    debits = defaultdict(list)
    open_amount: dict = {}
    total: dict = {}
    notes: list[str] = []
    for t in txns:
        k = classify(t, qtype)
        lines = _lines(t)
        if k:
            kind[t["trans"]] = k
        for i, line in enumerate(lines):
            acct = qtype.get(line["account"])
            if acct not in ("AR", "AP"):
                continue
            who = _who(t, line)
            amount = _q(line["debit"] - line["credit"])
            qb_open = _num(line["open"])
            key = (t["trans"], i)
            if acct == "AR" and amount > 0:
                if not k:
                    side[t["trans"]].append((INVOICE, i, who, amount))
                elif k != INVOICE:
                    continue
                total[key] = amount
                open_amount[key] = _q(qb_open) if qb_open is not None else ZERO
                receivables[who.lower()].append((t["date"], key, amount - open_amount[key]))
            elif acct == "AR" and amount < 0:
                if not k:
                    side[t["trans"]].append((PAYMENT, i, who, -amount))
                elif k != PAYMENT:
                    continue
                total[key] = -amount
                open_amount[key] = abs(_q(qb_open)) if qb_open is not None else ZERO
                credits[who.lower()].append((t["date"], key, -amount - open_amount[key]))
            elif acct == "AP" and amount < 0:
                if not k:
                    side[t["trans"]].append((BILL, i, who, -amount))
                elif k != BILL:
                    continue
                total[key] = -amount
                open_amount[key] = abs(_q(qb_open)) if qb_open is not None else ZERO
                payables[who.lower()].append((t["date"], key, -amount - open_amount[key]))
            elif acct == "AP" and amount > 0:
                if not k:
                    side[t["trans"]].append((BILL_PAYMENT, i, who, amount))
                elif k != BILL_PAYMENT:
                    continue
                total[key] = amount
                open_amount[key] = abs(_q(qb_open)) if qb_open is not None else ZERO
                debits[who.lower()].append((t["date"], key, amount - open_amount[key]))

    alloc: dict = {}
    short = []

    def apply(docs, pays, label):
        for who in set(docs) | set(pays):
            need = [[d, key, cap] for d, key, cap in sorted(docs.get(who, []), key=lambda x: (x[0], int(x[1][0]) if x[1][0].isdigit() else 0))]
            for _d, pkey, avail in sorted(pays.get(who, []), key=lambda x: (x[0], int(x[1][0]) if x[1][0].isdigit() else 0)):
                for row in need:
                    if avail <= 0:
                        break
                    if row[2] <= 0:
                        continue
                    take = min(avail, row[2])
                    alloc[(pkey, row[1])] = alloc.get((pkey, row[1]), ZERO) + take
                    row[2] -= take
                    avail -= take
                if avail > 0:
                    short.append((label, who, avail))
            for row in need:
                if row[2] > 0:
                    short.append((label, who, -row[2]))

    apply(receivables, credits, "customer")
    apply(payables, debits, "vendor")
    if short:
        notes.append(
            f"{len(short)} customer or vendor balances could not be paired exactly "
            f"from QuickBooks' open balances (first: {short[0][1]} {short[0][2]:,.2f}); "
            f"the ledger is unaffected, the document's open balance may differ"
        )
    return {
        "kind": kind,
        "side": dict(side),
        "alloc": alloc,
        "open": open_amount,
        "total": total,
        "notes": notes,
        "counts": {k: sum(1 for v in kind.values() if v == k) for k in DOC_KINDS},
    }


# ── making them ────────────────────────────────────────────────────────────


class Maker:
    """Creates the documents as the import posts the transactions."""

    def __init__(self, db, by_qb, qtype, docplan):
        from app.models.contacts import Customer, Vendor
        from app.models.invoices import Invoice
        from app.models.items import Item

        self.db = db
        self.by_qb = by_qb
        self.qtype = qtype
        self.p = docplan
        self.customers = {c.name.lower(): c for c in db.query(Customer).all()}
        self.vendors = {v.name.lower(): v for v in db.query(Vendor).all()}
        self.items = {i.name.lower(): i for i in db.query(Item).all()}
        self.numbers = {n for (n,) in db.query(Invoice.invoice_number).all()}
        self.docs: dict = {}  # key → (kind, document)
        self.made = defaultdict(int)

    def customer(self, name):
        from app.models.contacts import Customer

        name = name or "QuickBooks customer"
        found = self.customers.get(name.lower())
        if found is None:
            found = Customer(name=name[:200])
            self.db.add(found)
            self.db.flush()
            self.customers[name.lower()] = found
        return found

    def vendor(self, name):
        from app.models.contacts import Vendor

        name = name or "QuickBooks vendor"
        found = self.vendors.get(name.lower())
        if found is None:
            found = Vendor(name=name[:200])
            self.db.add(found)
            self.db.flush()
            self.vendors[name.lower()] = found
        return found

    def _invoice_number(self, t):
        num = (t["num"] or "").strip()[:40] or f"QB-{t['trans']}"
        if num in self.numbers:
            num = f"{num}-QB{t['trans']}"[:50]
        self.numbers.add(num)
        return num

    def _status(self, paid, total, unpaid, partial, full):
        if paid <= 0:
            return unpaid
        return full if paid >= total else partial

    # Each maker returns (source_type, source_id) for the posting, made
    # before it; link() points the document at the posting after.

    def invoice(self, t):
        from app.models.invoices import Invoice, InvoiceLine, InvoiceStatus

        lines = _lines(t)
        head = lines[0]
        key = (t["trans"], 0)
        who = self.customer(_who(t, head))
        total = _q(head["debit"] - head["credit"])
        open_amt = self.p["open"].get(key, ZERO)
        tax = ZERO
        rate = ZERO
        body = []
        for line in lines[1:]:
            amount = _q(line["credit"] - line["debit"])
            r = _rate(line["price"])
            if r is not None:
                tax += amount
                rate = rate or r
                continue
            body.append((line, amount))
        inv = Invoice(
            invoice_number=self._invoice_number(t),
            customer_id=who.id,
            status=InvoiceStatus.SENT,
            date=t["date"],
            due_date=_date(head["due"]) or t["date"],
            terms=(head["terms"] or "")[:50],
            subtotal=_q(total - tax),
            tax_rate=rate,
            tax_amount=tax,
            total=total,
            amount_paid=ZERO,
            balance_due=total,
            notes=(t["memo"] or None),
        )
        self.db.add(inv)
        self.db.flush()
        for order, (line, amount) in enumerate(body):
            item = self.items.get((line["item"] or "").lower()) if line["item"] else None
            qty = _num(line["qty"])
            qty = abs(qty) if qty else Decimal("1")
            price = _num(line["price"])
            self.db.add(
                InvoiceLine(
                    invoice_id=inv.id,
                    item_id=item.id if item else None,
                    description=(line["memo"] or line["item"] or line["account"])[:2000],
                    quantity=qty,
                    rate=price if price is not None else (amount / qty if qty else amount),
                    amount=amount,
                    is_taxable=(line["tax_code"] or "").upper() not in ("", "E", "Z", "NON"),
                    line_order=order,
                )
            )
        self.docs[key] = (INVOICE, inv)
        self.made[INVOICE] += 1
        return "invoice", inv.id

    def payment(self, t):
        from app.models.payments import Payment

        lines = _lines(t)
        head = lines[0]
        i, ar = next((i, l) for i, l in enumerate(lines) if self.qtype.get(l["account"]) == "AR")
        who = self.customer(_who(t, ar))
        pay = Payment(
            customer_id=who.id,
            date=t["date"],
            amount=_q(ar["credit"] - ar["debit"]),
            check_number=(t["num"] or None),
            reference=(t["num"] or None),
            deposit_to_account_id=self.by_qb[head["account"]].id,
            notes=(t["memo"] or None),
        )
        self.db.add(pay)
        self.db.flush()
        self.docs[(t["trans"], i)] = (PAYMENT, pay)
        self.made[PAYMENT] += 1
        return "payment", pay.id

    def bill(self, t):
        from app.models.bills import Bill, BillLine, BillStatus

        lines = _lines(t)
        head = lines[0]
        key = (t["trans"], 0)
        who = self.vendor(_who(t, head))
        total = _q(head["credit"] - head["debit"])
        bill = Bill(
            bill_number=((t["num"] or "").strip() or f"QB-{t['trans']}")[:100],
            vendor_id=who.id,
            status=BillStatus.UNPAID,
            date=t["date"],
            due_date=_date(head["due"]) or t["date"],
            terms=(head["terms"] or "")[:50],
            ref_number=(t["num"] or None),
            # HST paid is a line of its own, to its account, as QuickBooks
            # posted it — not tax added into the expense
            subtotal=total,
            tax_rate=ZERO,
            tax_amount=ZERO,
            total=total,
            amount_paid=ZERO,
            balance_due=total,
            notes=(t["memo"] or head["memo"] or None),
        )
        self.db.add(bill)
        self.db.flush()
        for order, line in enumerate(lines[1:]):
            amount = _q(line["debit"] - line["credit"])
            item = self.items.get((line["item"] or "").lower()) if line["item"] else None
            qty = _num(line["qty"])
            qty = abs(qty) if qty else Decimal("1")
            self.db.add(
                BillLine(
                    bill_id=bill.id,
                    item_id=item.id if item else None,
                    account_id=self.by_qb[line["account"]].id,
                    description=(line["memo"] or line["item"] or None),
                    quantity=qty,
                    rate=(amount / qty) if qty else amount,
                    amount=amount,
                    line_order=order,
                )
            )
        self.docs[key] = (BILL, bill)
        self.made[BILL] += 1
        return "bill", bill.id

    def bill_payment(self, t):
        from app.models.bills import BillPayment

        lines = _lines(t)
        head = lines[0]
        i, ap = next((i, l) for i, l in enumerate(lines) if self.qtype.get(l["account"]) == "AP")
        who = self.vendor(_who(t, ap))
        card = self.qtype.get(head["account"]) == "CCARD"
        bp = BillPayment(
            vendor_id=who.id,
            date=t["date"],
            amount=_q(ap["debit"] - ap["credit"]),
            method="credit_card" if card else "check",
            check_number=(t["num"] or None),
            pay_from_account_id=self.by_qb[head["account"]].id,
            notes=(t["memo"] or None),
        )
        self.db.add(bp)
        self.db.flush()
        self.docs[(t["trans"], i)] = (BILL_PAYMENT, bp)
        self.made[BILL_PAYMENT] += 1
        return "bill_payment", bp.id

    def void(self, t):
        """An invoice or bill QuickBooks voided (every amount 0.00)."""
        from app.models.bills import Bill, BillStatus
        from app.models.invoices import Invoice, InvoiceStatus

        head = t["lines"][0]
        tag = f"(QB #{t['trans']})"
        words = f"Void in QuickBooks {tag}" + (f": {t['memo']}" if t["memo"] else "")
        model = Invoice if (t["type"] or "").lower() == "invoice" else Bill
        if self.db.query(model.id).filter(model.notes.like(f"%{tag}%")).first():
            return  # brought over by an earlier upload
        if model is Invoice:
            doc = Invoice(
                invoice_number=self._invoice_number(t),
                customer_id=self.customer(_who(t, head)).id, status=InvoiceStatus.VOID,
                date=t["date"], due_date=_date(head["due"]) or t["date"],
                terms=(head["terms"] or "")[:50], subtotal=ZERO, tax_rate=ZERO,
                tax_amount=ZERO, total=ZERO, amount_paid=ZERO, balance_due=ZERO, notes=words,
            )
        else:
            doc = Bill(
                bill_number=((t["num"] or "").strip() or f"QB-{t['trans']}")[:100],
                vendor_id=self.vendor(_who(t, head)).id, status=BillStatus.VOID,
                date=t["date"], due_date=_date(head["due"]) or t["date"], terms="",
                subtotal=ZERO, tax_rate=ZERO, tax_amount=ZERO, total=ZERO,
                amount_paid=ZERO, balance_due=ZERO, notes=words,
            )
        self.db.add(doc)
        self.db.flush()
        self.made["void"] += 1

    def sides(self, t, txn_id):
        """A journal entry's receivable or payable, as a document beside it."""
        from app.models.bills import Bill, BillLine, BillPayment, BillStatus
        from app.models.invoices import Invoice, InvoiceLine, InvoiceStatus
        from app.models.payments import Payment

        for kind, i, who, amount in self.p["side"].get(t["trans"], []):
            words = f"QuickBooks journal entry QB #{t['trans']}" + (f": {t['memo']}" if t["memo"] else "")
            if kind == INVOICE:
                doc = Invoice(
                    invoice_number=self._invoice_number({"num": "", "trans": f"{t['trans']}-{i}"}),
                    customer_id=self.customer(who).id, status=InvoiceStatus.SENT,
                    date=t["date"], due_date=t["date"], terms="",
                    subtotal=amount, tax_rate=ZERO, tax_amount=ZERO, total=amount,
                    amount_paid=ZERO, balance_due=amount, notes=words,
                    transaction_id=txn_id,
                )
                self.db.add(doc)
                self.db.flush()
                self.db.add(InvoiceLine(invoice_id=doc.id, description=words, quantity=Decimal("1"),
                                        rate=amount, amount=amount, is_taxable=False, line_order=0))
            elif kind == PAYMENT:
                doc = Payment(customer_id=self.customer(who).id, date=t["date"], amount=amount,
                              reference=f"QB #{t['trans']}", notes=words, transaction_id=txn_id)
                self.db.add(doc)
            elif kind == BILL:
                doc = Bill(bill_number=f"QB-{t['trans']}", vendor_id=self.vendor(who).id,
                           status=BillStatus.UNPAID, date=t["date"], due_date=t["date"], terms="",
                           subtotal=amount, tax_rate=ZERO, tax_amount=ZERO, total=amount,
                           amount_paid=ZERO, balance_due=amount, notes=words, transaction_id=txn_id)
                self.db.add(doc)
                self.db.flush()
                self.db.add(BillLine(bill_id=doc.id, description=words, quantity=Decimal("1"),
                                     rate=amount, amount=amount, line_order=0))
            else:
                doc = BillPayment(vendor_id=self.vendor(who).id, date=t["date"], amount=amount,
                                  method="check", notes=words, transaction_id=txn_id)
                self.db.add(doc)
            self.db.flush()
            self.docs[(t["trans"], i)] = (kind, doc)
            self.made[f"{kind} (journal entry)"] += 1

    def link(self, t, txn_id):
        for key, (kind, doc) in self.docs.items():
            if key[0] == t["trans"] and getattr(doc, "transaction_id", None) is None:
                doc.transaction_id = txn_id

    def settle(self):
        """Apply payments to invoices and bill payments to bills, as planned,
        and set each document's paid amount, balance and status."""
        from app.models.bills import BillPaymentAllocation, BillStatus
        from app.models.invoices import InvoiceStatus
        from app.models.payments import PaymentAllocation

        paid = defaultdict(lambda: ZERO)
        for (pkey, dkey), amount in self.p["alloc"].items():
            if pkey not in self.docs or dkey not in self.docs:
                continue
            pkind, pay = self.docs[pkey]
            dkind, doc = self.docs[dkey]
            if pkind == PAYMENT and dkind == INVOICE:
                self.db.add(PaymentAllocation(payment_id=pay.id, invoice_id=doc.id, amount=amount))
            elif pkind == BILL_PAYMENT and dkind == BILL:
                self.db.add(BillPaymentAllocation(bill_payment_id=pay.id, bill_id=doc.id, amount=amount))
            else:
                continue
            paid[dkey] += amount
        for key, (kind, doc) in self.docs.items():
            if kind == INVOICE:
                done = paid[key]
                doc.amount_paid = done
                doc.balance_due = _q(doc.total - done)
                doc.status = (InvoiceStatus.PAID if doc.balance_due <= 0
                              else InvoiceStatus.PARTIAL if done > 0 else InvoiceStatus.SENT)
            elif kind == BILL:
                done = paid[key]
                doc.amount_paid = done
                doc.balance_due = _q(doc.total - done)
                doc.status = (BillStatus.PAID if doc.balance_due <= 0
                              else BillStatus.PARTIAL if done > 0 else BillStatus.UNPAID)
        self.db.flush()
