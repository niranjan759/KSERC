import re
import sys
from pathlib import Path

# Bare sibling imports below (and in arr_budget.py/petition_claims.py)
# resolve only when this directory is on sys.path. That happens for free
# when a script here is run standalone (Python adds its own directory),
# but NOT when this module is imported as `extraction.schema_discovery`
# from backend/main.py (app-dir is `backend`, so only `backend` itself is
# on sys.path there). This keeps both usages working without duplicating
# the module under two different import styles.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# A "serial" cell is a row/item number, not a field label: "1", "(a)", "I.",
# "II", "7" etc. Kept separate from the label so a leading serial column
# never gets mistaken for the label itself (see find_label).
SERIAL_PAT = re.compile(r'^\(?[a-zA-Z0-9]{1,3}\)?\.?$')
NUMERIC_CELL_PAT = re.compile(r'^[+-]?[\d,]+(\.\d+)?%?$')

# A table's unit is usually printed as a trailing parenthetical in its title
# ("...for the year 2023-24 (Rs. Cr)") when the table has no separate
# unit_row of its own (unit_row is only populated when pdfplumber found a
# standalone row of unit-only cells - see extract_sbu_g.is_unit_header_row).
UNIT_IN_TITLE_PAT = re.compile(r'\(([^()]*(?:Rs\.?|MU|kWh|%|MW|Cr|Lakh)[^()]*)\)\s*$', re.I)


def table_unit(table):
    """Best-effort unit string for a table: prefer its own unit_row (the
    extraction script already isolates this as a distinct row when present),
    falling back to a parenthetical in the title when there's no unit_row."""
    unit_row = table.get("unit_row")
    if unit_row:
        cells = [c.strip().strip("()") for c in unit_row if c and str(c).strip()]
        if cells:
            deduped = list(dict.fromkeys(cells))
            return deduped[0] if len(deduped) == 1 else " / ".join(deduped)
    m = UNIT_IN_TITLE_PAT.search(table.get("title") or "")
    return m.group(1).strip() if m else None


def find_label(row):
    """Return (label, label_idx, sl_no) for a data row.

    The label isn't always column 0 - tables routinely lead with one or more
    blank cells and/or a serial-number cell before the actual label (e.g.
    ['', '1', '', '', 'Employee Cost', ...] in Table 2.7/2.13's nested-header
    rows). Walk left to right, skip blanks, capture at most one leading
    serial-looking cell as sl_no, and take the first remaining non-numeric
    cell as the label. A row with no such cell (all blank, or nothing but
    numbers) has no label and is not a candidate field."""
    sl_no = None
    for i, cell in enumerate(row):
        c = (cell or "").strip()
        if not c:
            continue
        if sl_no is None and SERIAL_PAT.match(c) and i < len(row) - 1:
            sl_no = c
            continue
        if not NUMERIC_CELL_PAT.match(c.replace(" ", "")):
            return c, i, sl_no
    return None, None, sl_no


def row_has_data(row, label_idx):
    """A candidate field needs at least one numeric-looking value somewhere
    AFTER its label column - otherwise it's a section/group heading with no
    figures of its own (e.g. Table 2.11's 'Hydel Stations', 'Solar projects'
    rows), not a real field."""
    for cell in row[label_idx + 1:]:
        c = (cell or "").strip()
        if c and NUMERIC_CELL_PAT.match(c.replace(" ", "")):
            return True
    return False


def discover_schema(order_tables):
    """Given the `order_tables` list from extract_sbu_g.extract_section(),
    infer the document's field schema: for every table, which row labels
    represent actual data fields (as opposed to section headings or
    unlabeled rows). This is intentionally NOT deduplicated across tables -
    the same concept (e.g. "Depreciation") legitimately reappears in
    multiple summary tables in these documents (see Table 2.2 vs 2.18 vs
    2.19), and collapsing that here would throw away real structure. Cross-
    table/cross-document deduplication into canonical concept keys is the
    field-matching registry's job (stage iii design), not this stage's."""
    fields = []
    for t in order_tables:
        unit = table_unit(t)
        for row_idx, row in enumerate(t.get("data_rows", [])):
            label, label_idx, sl_no = find_label(row)
            if label is None or label_idx is None:
                continue
            if not row_has_data(row, label_idx):
                continue
            fields.append({
                "table_no": t.get("table_no"),
                "table_title": t.get("title"),
                "sl_no": sl_no,
                "field_label": label,
                "unit": unit,
                "columns": t.get("header"),
                "pages": t.get("pages"),
                "row_index": row_idx,
                "table_needs_review": t.get("needs_review", False),
            })
    return fields


def discover_schema_from_pdf(pdf_path):
    from extract_sbu_g import extract_section
    result = extract_section(pdf_path)
    if "error" in result:
        return result
    fields = discover_schema(result["order_tables"])
    return {
        "source_pdf": pdf_path,
        "chapter_heading": result["chapter_heading"],
        "pages": result["pages"],
        "table_count": len(result["order_tables"]),
        "field_count": len(fields),
        "fields": fields,
    }


if __name__ == "__main__":
    import json
    import sys

    pdf_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not pdf_path:
        print("Usage: python schema_discovery.py <path-to-truing-up-order.pdf>")
        sys.exit(1)

    out = discover_schema_from_pdf(pdf_path)
    if "error" in out:
        print(out["error"])
        sys.exit(1)

    print(f"Chapter: {out['chapter_heading']}  | pages {out['pages'][0]}-{out['pages'][1]}")
    print(f"Tables: {out['table_count']}  | Discovered fields: {out['field_count']}")
    by_table = {}
    for f in out["fields"]:
        by_table.setdefault(f["table_no"], []).append(f)
    for table_no, flds in by_table.items():
        print(f"\n  Table {table_no} | {flds[0]['table_title']}")
        for f in flds:
            sl = f"{f['sl_no']}. " if f["sl_no"] else ""
            unit = f" [{f['unit']}]" if f["unit"] else ""
            print(f"    {sl}{f['field_label']}{unit}")

    out_path = "schema_output.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nWrote {out_path}")
