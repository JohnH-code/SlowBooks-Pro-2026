"""A cheque's memo line (John's build).

A scanned receipt left "Tax detected: $83.96" in a bill's memo; the bill's
payment carried it to the cheque. The memo line drops that note and puts
what is left on one line.
"""

import re

_TAX_NOTE = re.compile(r"^\s*Tax detected:.*$", re.IGNORECASE)


def cheque_memo(text) -> str:
    lines = [ln.strip() for ln in str(text or "").splitlines()]
    return " ".join(ln for ln in lines if ln and not _TAX_NOTE.match(ln))
