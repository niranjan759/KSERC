"""Identify what kind of regulatory document an upload is, and which year(s)
it covers, so a comparison can refuse a document placed in the wrong slot
(e.g. a petition in the ARR slot) instead of silently producing meaningless
numbers."""
import re

import pdfplumber

DOC_TYPES = ("truing_up_order", "arr", "petition")
DOC_TYPE_LABELS = {
    "truing_up_order": "Truing Up Order",
    "arr": "ARR order",
    "petition": "Truing-up petition",
    "unknown": "Unrecognised document",
}

YEAR_PAT = re.compile(r'(\d{4})\s*[-–—]\s*(\d{2,4})')


def normalize_year(text):
    """'2024-25', '2024-2025', 'FY 2024–25' -> '2024-25'; None if the text
    isn't a financial year whose second half follows the first."""
    m = YEAR_PAT.search(text or "")
    if not m:
        return None
    start = int(m.group(1))
    end = m.group(2)
    end_full = int(end) if len(end) == 4 else int(str(start)[:2] + end)
    if end_full != start + 1:
        return None
    return f"{start}-{str(end_full)[-2:]}"


def _year_range(first, last):
    a, b = int(first[:4]), int(last[:4])
    return [f"{y}-{str(y + 1)[-2:]}" for y in range(a, b + 1)]


def _first_pages_text(pdf_path, n=2):
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages[:n])


def classify(data, pdf_path):
    """Score each document type from several independent signals - no single
    phrase is relied on, because first-page text is sometimes badly garbled
    (the 2023-24 petition's cover reads "I(ERALA STATE ... COMM ISSIOhI")."""
    text = _first_pages_text(pdf_path)
    upper = text.upper()
    heading = (data.get("chapter_heading") or "").upper()
    table_nos = [t["table_no"] for t in data.get("order_tables", []) if t.get("table_no")]
    lettered = sum(1 for n in table_nos if re.match(r'^[A-Z]', n))
    decimal = sum(1 for n in table_nos if re.match(r'^\d+\.\d+$', n))

    score = {k: 0 for k in DOC_TYPES}
    if "FILING NO" in upper:
        score["petition"] += 2
    if "BEFORE THE HONOURABLE" in upper:
        score["petition"] += 1
    if "TRUING-UP OF ARR" in heading or "TRUING UP OF ARR" in heading:
        score["petition"] += 1
    if table_nos and lettered > len(table_nos) / 2:
        score["petition"] += 2

    if "ORDER DATED" in upper or ("PRESENT" in upper and "CHAIRMAN" in upper):
        score["truing_up_order"] += 2
    if "TRUING UP OF ACCOUNTS OF STRATEGIC BUSINESS UNIT" in heading:
        score["truing_up_order"] += 2

    if "CONTROL PERIOD" in upper or "ARR, ERC AND TARIFF" in upper:
        score["arr"] += 2
    if "ARR&ERC" in heading.replace(" ", ""):
        score["arr"] += 2

    if table_nos and decimal > len(table_nos) / 2:
        score["truing_up_order"] += 1
        score["arr"] += 1

    best = max(score, key=score.get)
    doc_type = best if score[best] >= 3 else "unknown"

    fiscal_year = None
    control_period = []
    if doc_type == "arr":
        m = re.search(r'CONTROL\s+PERIOD\s+(\d{4}\s*-\s*\d{2,4})\s+TO\s+(\d{4}\s*-\s*\d{2,4})', upper)
        if m and normalize_year(m.group(1)) and normalize_year(m.group(2)):
            control_period = _year_range(normalize_year(m.group(1)), normalize_year(m.group(2)))
    else:
        m = re.search(r'(?:FINANCIAL\s+)?YEAR\s+(\d{4}\s*[-–]\s*\d{2,4})', upper)
        if m:
            fiscal_year = normalize_year(m.group(1))
        if not fiscal_year:
            years = [normalize_year(t.get("title") or "") for t in data.get("order_tables", [])]
            years = [y for y in years if y]
            if years:
                fiscal_year = max(set(years), key=years.count)

    return {"doc_type": doc_type, "fiscal_year": fiscal_year, "control_period": control_period}


def with_article(label):
    return ("an " if label[:1].upper() in "AEIOU" else "a ") + label


def describe(meta):
    label = DOC_TYPE_LABELS.get(meta.get("doc_type"), "Unrecognised document")
    if meta.get("control_period"):
        return f"{label} ({meta['control_period'][0]} to {meta['control_period'][-1]})"
    if meta.get("fiscal_year"):
        return f"{label} (FY {meta['fiscal_year']})"
    return label
