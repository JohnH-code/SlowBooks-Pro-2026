# ============================================================================
# Memorized transactions — QuickBooks' Memorized Transaction List: a cheque,
# bill, deposit, journal entry or invoice kept as a pattern, entered again on
# a schedule (or by hand), with a reminder when it comes due or entered
# automatically. services/memorized.py does the work.
# ============================================================================

from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String, Text, func

from app.database import Base


class MemorizedTransaction(Base):
    __tablename__ = "memorized_transactions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    # expense | bill | deposit | journal | invoice
    kind = Column(String(20), nullable=False)
    # the create request (JSON) the route takes, without its date
    payload = Column(Text, nullable=False)
    # never | weekly | biweekly | monthly | quarterly | semiannually | annually
    frequency = Column(String(20), nullable=False, default="monthly")
    next_date = Column(Date, nullable=True)
    # remind | auto | none
    action = Column(String(10), nullable=False, default="remind")
    days_in_advance = Column(Integer, nullable=False, default=0)
    # entries left; NULL = no end
    remaining = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    last_entered = Column(Date, nullable=True)
    times_entered = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
