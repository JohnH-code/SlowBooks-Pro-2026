from datetime import date as dt_date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field
from app.schemas.common import StrictModel


class ExpenseLineIn(StrictModel):
    """One split of a cheque or card payment: an account and its amount. A
    negative amount is a credit on the cheque (a refund or a deposit netted
    against it), as QuickBooks' Write Cheques allows."""

    account_id: int
    amount: Decimal
    memo: Optional[str] = Field(None, max_length=300)
    class_id: Optional[int] = None
    job_id: Optional[int] = None
    # Canadian GST/HST: "H" = taxable, the tax is an input tax credit posted
    # to the GST/HST account; "E" or none = no tax on the line.
    tax_code: Optional[str] = Field(None, pattern="^(H|E)?$")


class ExpenseCreate(StrictModel):
    """One paid receipt: money already left a bank or credit-card account.
    DR expense account(s), CR the account it was paid from.

    Either one account and an amount (expense_account_id + amount), or a
    split across several (lines) — a cheque for a fee and its HST, say. With
    lines, the amount paid is their total."""

    date: dt_date
    vendor_id: Optional[int] = None
    payee: Optional[str] = Field(None, max_length=200)
    expense_account_id: Optional[int] = None
    paid_from_account_id: int
    amount: Optional[Decimal] = None
    lines: list[ExpenseLineIn] = []
    reference: Optional[str] = Field(None, max_length=100)
    memo: Optional[str] = None
    class_id: Optional[int] = None
    job_id: Optional[int] = None
    cost_code_id: Optional[int] = None
    function: Optional[str] = None  # nonprofit: program | management | fundraising
    is_billable: bool = False
    # the one-account form's GST/HST code (see ExpenseLineIn.tax_code)
    tax_code: Optional[str] = Field(None, pattern="^(H|E)?$")
    # the taxable amounts already include the GST/HST (a receipt's total)
    amounts_include_tax: bool = False


class ExpenseLineOut(BaseModel):
    account_id: int
    account_name: str = ""
    account_number: str = ""
    amount: float
    memo: str = ""


class ExpenseResponse(BaseModel):
    id: int
    date: dt_date
    payee: str = ""
    vendor_id: Optional[int] = None
    expense_account_name: str = ""
    paid_from_account_name: str = ""
    # bank | credit_card: a cheque prints only from a bank account
    paid_from_kind: str = ""
    amount: float
    reference: str = ""
    memo: str = ""
    status: str = "recorded"  # "recorded" | "void"
    printable: bool = False  # paid from a bank account and not void: Print Check
    # every account the payment went to; one line for a simple expense
    lines: list[ExpenseLineOut] = []
