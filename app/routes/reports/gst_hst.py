# ============================================================================
# GST/HST return (Canada) — services/hst.py does the work.
# ============================================================================

from datetime import date

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.reports._router import router
from app.services import hst


@router.get("/gst-hst-return/periods")
def gst_hst_periods(db: Session = Depends(get_db)):
    """The company's GST/HST settings and its recent filing periods, newest
    first, with the one to file now."""
    ps, due = hst.current_periods(db)
    return {
        "enabled": hst.account_id(db) is not None,
        "frequency": hst.frequency(db),
        "periods": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in ps],
        "due": (
            {"start": due[0].isoformat(), "end": due[1].isoformat()} if due else None
        ),
    }


@router.get("/gst-hst-return")
def gst_hst_return(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db),
):
    return hst.gst_hst_return(db, start_date, end_date)
