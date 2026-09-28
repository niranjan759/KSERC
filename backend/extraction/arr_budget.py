import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_discovery import find_label, table_unit

YEAR_PAT = re.compile(r'(\d{4})\s*-\s*(\d{2,4})')


def _normalize(label):
    label = (label or "").lower()
    label = label.replace("&", "and")
    label = re.sub(r'[^a-z0-9 ]', ' ', label)
    return re.sub(r'\s+', ' ', label).strip()


def _year_key(cell):
    """Extract a normalized "YYYY-YY" key from a header cell. ARR tables
    print years in several ways in the same document - "2023-24",
    "2023- 24" (stray space from a wrapped cell), "MYT period 2022-23"
    (extra prefix text) - so this matches the year pattern anywhere in the
    cell rather than requiring the cell to be just the year."""
    m = YEAR_PAT.search(cell or "")
    if not m:
        return None
    start, end = m.group(1), m.group(2)
    end = end if len(end) == 4 else start[:2] + end
    return f"{start}-{end[-2:]}"


def _approved_year_values(header, row, label_idx):
    """Map {year: value} for a row's data columns. Some ARR tables print
    KSEBL's claimed figures and KSERC's approved figures side by side for
    the SAME years (e.g. Table 4.22/4.23/4.53: "...Petition 2022-23,
    2023-24, ... KSERC Approval 2022-23, 2023-24, ..."). Using only the
    approval half of the header avoids picking up the claimed figure by
    accident. A table with a single set of year columns (already-approved
    tables like 4.30/4.60/4.63, whose titles say "approved") is used as
    given - there's nothing to split."""
    cells = header[label_idx + 1:]
    row_vals = row[label_idx + 1:]
    approval_start = None
    for i, c in enumerate(cells):
        if c and re.search(r'approv', c, re.I):
            approval_start = i
            break
    if approval_start is not None:
        cells = cells[approval_start:]
        row_vals = row_vals[approval_start:]
    out = {}
    for c, v in zip(cells, row_vals):
        yk = _year_key(c)
        if yk:
            out[yk] = v
    return out


def find_row_in_table(order_tables, table_no, row_label):
    for t in order_tables:
        if t.get("table_no") != table_no:
            continue
        header = t.get("header") or []
        for row in t.get("data_rows", []):
            label, label_idx, sl_no = find_label(row)
            if label and _normalize(label) == _normalize(row_label):
                return t, row, header, label_idx
    return None


# Curated mapping from a stage-1 schema field (identified by its exact
# label AND the Truing Up Order table TITLE it's legitimately sourced
# from - see below on why title, not table number) to the ARR table/row
# that carries the Commission's APPROVED figure for that same concept.
#
# This is deliberately NOT a generic fuzzy matcher. Every single mapping
# below was hand-verified: the ARR-approved value pulled via this mapping
# for FY2023-24 and FY2024-25 matches the corresponding Truing Up Order's
# own reprint of that figure EXACTLY (e.g. ARR Table 4.60's 2023-24
# "Return on Equity" = 116.38 = Truing Up Order 23-24's Table 2.2 "RoE"
# 2023-24 column = 116.38). A premature generic matcher risks silently
# pairing the wrong rows across two large, differently-worded documents;
# this narrow, explicit list only claims what's actually been checked.
#
# `source_title_pattern` matches against the schema field's TABLE TITLE,
# not its table number - table numbers shift year to year (the 2023-24
# Truing Up Order's final summary is Table 2.19; the 2024-25 order has
# fewer sub-tables that year, so the SAME summary is Table 2.16 there),
# exactly the kind of numbering drift finding #2 already warned about.
# Matching on the stable title wording ("Transfer Cost of SBU-G" appears
# in both the claimed and the KSERC-approved summary tables, every year)
# survives that drift; matching on a literal table number doesn't -
# confirmed by this exact bug: an earlier, table-number-scoped version of
# this map silently dropped "Additional contribution to Master Trust" for
# FY2024-25 because it only recognized Table 2.19, which doesn't exist
# under that number in the 2024-25 document.
#
# The pattern still exists (rather than matching on field_label alone)
# because some field labels are too generic to match across the WHOLE
# schema - e.g. "Total" is a bare row label in the O&M sub-breakdown table
# but ALSO appears as an unrelated row in physical-generation tables (MU
# totals, not Rs. Cr costs). Scoping to a title pattern prevents a mapping
# entry from firing on an unrelated same-named row elsewhere in the
# schema.
#
# `arr_table_no is None` means: checked, and there IS no separate
# ARR-approved budget line for this field - the Truing Up Order's own
# "MYT Order"/"ARR Approval" column already shows 0.00 or blank for it,
# consistent with the ARR simply not having budgeted anything under that
# head. That's a confirmed absence, not a gap in the mapping.
ARR_FIELD_MAP = [
    ("Cost of Generation of Power", r'Transfer Cost of SBU-G', None, None,
     "not budgeted as a separate ARR line; the Truing Up Order's own MYT-approved value is 0.00"),
    ("O&M Expenses for existing stations", r'Transfer Cost of SBU-G', "4.22", "Existing stations", None),
    ("O&M Expenses for new stations", r'Transfer Cost of SBU-G', "4.22", "New Stations", None),
    ("O&M Expenses - Total", r'Transfer Cost of SBU-G', "4.22", "Total", None),
    ("O&M expenses", r'Transfer Cost of SBU-G', "4.22", "Total", None),
    ("Interest & Finance Charges", r'Transfer Cost of SBU-G', "4.53", "Total Interest & Finance Charges", None),
    ("Depreciation", r'Transfer Cost of SBU-G', "4.30", "Total depreciation allowable during the year", None),
    ("Repayment of master Trust Bond", r'Transfer Cost of SBU-G', "4.60", "Repayment of master trust bond", None),
    ("Additional contribution to Master Trust", r'Transfer Cost of SBU-G', "4.60", "Additional contribution to master trust", None),
    ("Amortisation of intangible assets", r'Transfer Cost of SBU-G', None, None,
     "not budgeted as a separate ARR line; the Truing Up Order's own MYT-approved value is 0.00"),
    ("RoE", r'Transfer Cost of SBU-G', "4.60", "Return on Equity", None),
    ("Exceptional Items", r'Transfer Cost of SBU-G', None, None,
     "not budgeted as a separate ARR line; the Truing Up Order's own MYT-approved value is blank/0"),
    ("Others", r'Transfer Cost of SBU-G', None, None,
     "not budgeted as a separate ARR line; the Truing Up Order's own MYT-approved value is blank/0"),
    ("ARR", r'Transfer Cost of SBU-G', "4.60", "Aggregate Revenue Requirement", None),
    ("Less Non-Tariff Income", r'Transfer Cost of SBU-G', "4.63", "Less Other Income", None),
    ("Net ARR (Transferred to SBU-D)", r'Transfer Cost of SBU-G', "4.63", "Net ARR of SBU G", None),
    ("Employee Cost", r'O&M (expenses|cost) of SBU-G claimed', "4.23", "Employee expense", None),
    ("A&G Expenses", r'O&M (expenses|cost) of SBU-G claimed', "4.23", "A&G expenses", None),
    ("R&M Expenses", r'O&M (expenses|cost) of SBU-G claimed', "4.23", "R&M expenses", None),

    # Interest & Finance Charges sub-items (Table 2.12/2.14/2.15/2.18,
    # titled "Interest and finan[ce/cing] charges..." across the two
    # petition years' numbering) - source ARR Table 4.53, the same table
    # already used for the "Interest & Finance Charges" top-level total.
    # Verified: ARR 4.53's 2024-25 approval column for each of these rows
    # matches Petition G10's own "Approved" column exactly (e.g. Interest
    # on Capital Liabilities: 140.26 in both).
    ("Interest on Capital Liabilities", r'Interest and financ\w* charges', "4.53", "Interest on capital liabilities", None),
    ("Interest on GPF", r'Interest and financ\w* charges', "4.53", "Interest on GPF", None),
    ("Interest on Working capital", r'Interest and financ\w* charges', "4.53", "Interest on working capital", None),
    ("Interest on Master Trust Bonds", r'Interest and financ\w* charges', "4.53", "Interest on Bonds issued to Master Trust", None),
    ("Sub Total", r'Interest and financ\w* charges', "4.53", "Total Interest & Finance Charges", None),
    ("Other Interests", r'Interest and financ\w* charges', None, None,
     "not budgeted as a separate ARR line; the Truing Up Order's own MYT-approved value is 0.00"),
    ("Less: Capitalized", r'Interest and financ\w* charges', None, None,
     "not budgeted as a separate ARR line; the Truing Up Order's own MYT-approved value is 0.00"),
    ("Balance", r'Interest and financ\w* charges', None, None,
     "equals Sub Total less Capitalized - not a separate ARR-budgeted line"),
]


def _lookup_map(field_label, schema_table_title):
    for entry_label, title_pattern, arr_table_no, arr_row_label, note in ARR_FIELD_MAP:
        if entry_label == field_label and re.search(title_pattern, schema_table_title or "", re.I):
            return arr_table_no, arr_row_label, note
    return None


def extract_arr_budget(schema_fields, arr_order_tables, target_year):
    """For each stage-1 schema field covered by ARR_FIELD_MAP, pull the
    ARR-approved figure for `target_year` (e.g. "2023-24"). Fields not in
    the map at all (the schema's many granular/detail rows - monthly
    generation, per-project O&M, etc.) are left out entirely rather than
    force-matched to something unrelated; see ARR_FIELD_MAP's docstring
    for what IS covered and why. One result per unique field_label (the
    same concept can appear in more than one Truing Up Order table; the
    first matching occurrence is used)."""
    results = []
    seen = set()
    for f in schema_fields:
        label = f["field_label"]
        if label in seen:
            continue
        entry = _lookup_map(label, f["table_title"])
        if entry is None:
            continue
        seen.add(label)
        arr_table_no, arr_row_label, note = entry

        if arr_table_no is None:
            results.append({
                "field_label": label,
                "schema_table_no": f["table_no"],
                "arr_table_no": None,
                "arr_row_label": None,
                "unit": f["unit"],
                "approved_value": None,
                "approved_by_year": {},
                "pages": [],
                "needs_review": False,
                "note": note,
            })
            continue

        found = find_row_in_table(arr_order_tables, arr_table_no, arr_row_label)
        if found is None:
            results.append({
                "field_label": label,
                "schema_table_no": f["table_no"],
                "arr_table_no": arr_table_no,
                "arr_row_label": arr_row_label,
                "unit": f["unit"],
                "approved_value": None,
                "approved_by_year": {},
                "pages": [],
                "needs_review": False,
                "note": "expected ARR row not found - mapping needs re-checking",
            })
            continue

        t, row, header, label_idx = found
        by_year = _approved_year_values(header, row, label_idx)
        results.append({
            "field_label": label,
            "schema_table_no": f["table_no"],
            "arr_table_no": arr_table_no,
            "arr_row_label": arr_row_label,
            "unit": table_unit(t) or f["unit"],
            "approved_value": by_year.get(target_year),
            "approved_by_year": by_year,
            "pages": t.get("pages", []),
            "needs_review": bool(t.get("needs_review")),
            "note": note,
        })
    return results


if __name__ == "__main__":
    import json
    import sys

    from extract_sbu_g import extract_section
    from schema_discovery import discover_schema

    if len(sys.argv) < 4:
        print("Usage: python arr_budget.py <truing-up-order.pdf> <arr.pdf> <target-year e.g. 2023-24>")
        sys.exit(1)

    tuo_path, arr_path, target_year = sys.argv[1], sys.argv[2], sys.argv[3]

    tuo_result = extract_section(tuo_path)
    if "error" in tuo_result:
        print("Truing Up Order:", tuo_result["error"])
        sys.exit(1)
    schema_fields = discover_schema(tuo_result["order_tables"])

    arr_result = extract_section(arr_path)
    if "error" in arr_result:
        print("ARR:", arr_result["error"])
        sys.exit(1)

    budget = extract_arr_budget(schema_fields, arr_result["order_tables"], target_year)

    covered = [b for b in budget if b["approved_value"] is not None]
    no_line = [b for b in budget if b["arr_table_no"] is None]
    missing = [b for b in budget if b["arr_table_no"] is not None and b["approved_value"] is None]

    print(f"Schema fields: {len(schema_fields)}  | Mapped fields: {len(budget)}")
    print(f"  with an ARR-approved {target_year} value: {len(covered)}")
    print(f"  confirmed no separate ARR budget line: {len(no_line)}")
    print(f"  mapping problem (expected row not found): {len(missing)}")
    print()
    for b in budget:
        val = b["approved_value"] if b["approved_value"] is not None else (b["note"] or "?")
        print(f"  [{b['schema_table_no']}] {b['field_label']:<45} -> {val}  {('(' + b['unit'] + ')') if b['unit'] else ''}")

    with open("arr_budget_output.json", "w", encoding="utf-8") as fh:
        json.dump({"target_year": target_year, "fields": budget}, fh, indent=2)
    print("\nWrote arr_budget_output.json")
