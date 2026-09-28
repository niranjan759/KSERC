import re
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_discovery import find_label, table_unit

# Petition tables whose field labels match the Truing Up Order's own
# schema labels verbatim (confirmed per table below), so - unlike stage
# (ii)'s ARR mapping - no alias table is needed, just a title pattern to
# find the table and column patterns to find its claimed-value column.
# Each table uses its OWN wording for these columns (Table G8: "ARR
# Approval"/"Actuals"/"TU Sought"; Table G10: "Approved"/"Actual"/"TU") -
# genuinely different words for the same concept, not a typo, so each
# needs its own patterns rather than one shared set.
#
# `recover` enables recover_g8_tail's page-break recovery (finding #13) -
# scoped to G8 specifically, since that's the only table this fallback has
# been verified against; a different table hitting the same failure mode
# would need its own canonical-order list before trusting this recovery.
#
# `tuo_title_pattern` scopes which TUO schema table(s) a petition table's
# rows are allowed to match against - matched against the schema field's
# OWN table_title in match_schema_to_petition, the same way ARR_FIELD_MAP
# scopes its entries. Without this, a generic label like "Sub total" that
# appears in more than one place - once in G10's interest breakdown, once
# in an UNRELATED per-project O&M subtotal in TUO Table 2.9 - gets
# silently cross-matched: confirmed as a real bug, where TUO 2.9's "Sub
# total" (a hydel-project O&M rollup) picked up G10's interest-charges
# claimed value purely because both normalize to the same label text.
PETITION_TABLES = [
    {
        # "ARR OF GENERATION BUSINESS UNIT (SBU-G) for <year>" - confirmed
        # identical row labels/order to TUO Table 2.2/2.19.
        "title_pattern": r'ARR OF GENERATION BUSINESS UNIT',
        "tuo_title_pattern": r'Transfer Cost of SBU-G',
        "approval_pat": r'ARR\s*Approval',
        "actuals_pat": r'Actual',
        "claimed_pat": r'TU\s*Sought',
        "recover": True,
    },
    {
        # "Interest and Finance charges (Rs Cr)" - confirmed identical row
        # labels to TUO Table 2.12/2.14/2.15/2.18's Interest & Finance
        # Charges breakdown, and its "Approved" column matches ARR Table
        # 4.53's approval column exactly (e.g. Interest on Capital
        # Liabilities, FY2024-25: 140.26 in both).
        "title_pattern": r'Interest and [Ff]inance charges',
        "tuo_title_pattern": r'Interest and financ\w* charges',
        "approval_pat": r'^Approved$',
        "actuals_pat": r'Actual',
        "claimed_pat": r'^TU$',
        "recover": False,
    },
]

# G8's canonical row order - verified identical across every document
# examined this session (both Truing Up Orders' Table 2.2/2.19, the ARR's
# own control-period summary tables, and the 2023-24 petition's own G8).
# Used only by recover_g8_tail as a last-resort recovery aid when this
# table's tail rows are lost to a page-break rendering quirk (see that
# function) - never used to override rows that extracted normally.
G8_CANONICAL_ORDER = [
    "Cost of Generation of Power",
    "O&M Expenses for existing stations",
    "O&M Expenses for new stations",
    "O&M Expenses - Total",
    "Interest & Finance Charges",
    "Depreciation",
    "Repayment of master Trust Bond",
    "Additional contribution to Master Trust",
    "Amortisation of intangible assets",
    "RoE",
    "Exceptional Items",
    "Others",
    "ARR",
    "Less Non-Tariff Income",
    "Net ARR (Transferred to SBU-D)",
]

NUM_TOKEN_PAT = re.compile(r'^\(?-?[\d,]+(\.\d+)?\)?%?$')
TABLE_MARKER_LINE_PAT = re.compile(r'^[\s"“‘\'”’]*Table', re.I)

# Deliberately no "difference" column extracted for any table here.
# G8's own "Difference over approval" TEXT sits one column to the right of
# where its VALUE actually lands (confirmed: for every row, the real
# difference value is under a blank-header column immediately before the
# "Difference over approval" header cell, not under that cell itself - a
# distinct, table-wide header/value offset, not the same per-row shift
# _realign_row fixes). Rather than bolt on a second undertested repair for
# a value this pipeline doesn't need, deviation is computed downstream
# from claimed - approved directly (matching the brief's own design: the
# system computes the deviation, it doesn't copy the document's printed
# one), so the unreliable column is simply not extracted.


def _normalize(label):
    label = (label or "").lower()
    label = label.replace("&", "and")
    label = re.sub(r'[^a-z0-9 ]', ' ', label)
    return re.sub(r'\s+', ' ', label).strip()


def _realign_row(header, row):
    """Some rows land with one extra filler cell relative to the header -
    confirmed on Petition Table G8's "Net ARR (Transferred to SBU-D)" row,
    where a real value ends up under a None-header (pure padding) column
    while the column it actually belongs to sits blank instead. Detected
    by a non-empty value showing up under a None-header position - padding
    columns are blank in every other row of this table, so that's a
    reliable signal something shifted. Repaired by dropping the blank cell
    immediately before it (the extra split that caused the shift) and
    re-padding the row's length at the end, which restores alignment for
    every column from that point on without disturbing anything before it.

    This is a narrow, targeted repair for one observed pattern, not a
    general realignment algorithm - if it starts firing on a table shaped
    differently than G8, verify the result against the source PDF the same
    way this one was, don't assume it generalizes."""
    fixed = list(row)
    for i, h in enumerate(header):
        if h is None and i < len(fixed) and fixed[i] not in (None, ""):
            if i > 0 and fixed[i - 1] in (None, ""):
                del fixed[i - 1]
                fixed.append(None)
            break
    return fixed


def table_offset(header, row_label_idx):
    """Some tables carry a constant column offset between their header and
    every data row - confirmed on the 2023-24 petition's Table G10, where
    ALL values (including the row label itself) sit exactly one column to
    the LEFT of their header text, consistently across all 8 rows (the
    SAME table in the 2024-25 petition has no such offset - a
    document-specific pdfplumber cell-splitting difference, not something
    tied to the table's identity). This is a different failure mode than
    _realign_row's single-row shift on G8's Net ARR row - that one is a
    per-row anomaly with a real value trapped under a None-header padding
    column; this one is a whole-table shift with no such marker, so it has
    to be detected by comparing WHERE the header's own label column
    ("Particulars") sits against where find_label() actually found the
    label in a real data row, and correcting every column lookup by that
    same difference. Verified: with this correction, Table G10's five
    interest sub-item claimed ("TU") values for FY2023-24 sum to exactly
    155.96, matching the already-verified top-level Interest & Finance
    Charges claimed figure."""
    if row_label_idx is None:
        return 0
    header_label_idx = next((i for i, h in enumerate(header) if h and re.search(r'Particulars', h, re.I)), None)
    if header_label_idx is None:
        return 0
    return header_label_idx - row_label_idx


def find_column_value(header, row, column_pattern, offset=0):
    row = _realign_row(header, row)
    for i, h in enumerate(header):
        if h and re.search(column_pattern, h, re.I):
            idx = i - offset
            return row[idx] if 0 <= idx < len(row) else None
    return None


def _trailing_numeric_values(text, count=4):
    """The last `count` whitespace-separated tokens of a line, if ALL of
    them look numeric - taken from the END specifically, not the start,
    because a row's leading serial number ("12") is otherwise
    indistinguishable from a real value on a line where the label itself
    is missing (see recover_g8_tail)."""
    tokens = text.split()
    if len(tokens) < count:
        return None
    tail = tokens[-count:]
    if all(NUM_TOKEN_PAT.match(t) for t in tail):
        return tail
    return None


def recover_g8_tail(pdf_path, table, found_labels):
    """Recover Table G8's trailing rows when they were lost to a
    page-break rendering quirk: pdfplumber sometimes renders a
    continuation page's version of this SAME table with a different raw
    column count than the table's own header, which fails
    extract_sbu_g's exact-column-count continuation check entirely - the
    row never merges into ANY table object, not even as an unclassified
    fragment (confirmed on the 2024-25 petition: G8 closes after row "10
    Others" on page 16; its true rows 11-13 - "ARR", "Less Non-Tariff
    Income", "Net ARR" - land on page 17, with row 11 not inside any
    pdfplumber table object on that page whatsoever, and rows 12-13
    inside a table object with 6 raw columns instead of G8's 9).

    Recovers those rows directly from raw PDF text on the page(s)
    immediately after G8's own last recorded page, using
    G8_CANONICAL_ORDER to know which field label is expected next rather
    than re-deriving the label from text that may itself be wrapped
    across several physical lines (confirmed: "Net ARR (Transferred to
    SBU-D)"'s row splits across 3 separate lines in the source PDF, with
    the numeric values sitting on the middle one). A candidate line is
    only trusted when its LAST 4 whitespace-separated tokens are all
    numeric-looking - ARR Approval, Actuals, TU Sought, Difference, in
    that fixed column order (Difference is recovered but not kept, for
    the same reason find_column_value never extracts it - see this
    module's opening comment). Scanning stops at the next "Table" marker
    line even if fields are still missing - it's safer to leave a field
    unrecovered than to risk pulling a value from an unrelated table
    that happens to also end in 4 numbers."""
    missing = [lbl for lbl in G8_CANONICAL_ORDER if lbl not in found_labels]
    if not missing:
        return []

    last_page = table["pages"][-1]  # 1-indexed
    recovered = []
    unit = table_unit(table)
    with pdfplumber.open(pdf_path) as pdf:
        for pnum in range(last_page, min(last_page + 2, len(pdf.pages))):
            if not missing:
                break
            for line in pdf.pages[pnum].extract_text_lines():
                if not missing:
                    break
                if TABLE_MARKER_LINE_PAT.match(line["text"].strip()):
                    missing = []
                    break
                vals = _trailing_numeric_values(line["text"])
                if vals is None:
                    continue
                label = missing.pop(0)
                recovered.append({
                    "field_label": label,
                    "unit": unit,
                    "table_no": table.get("table_no"),
                    "arr_approval": vals[0],
                    "actuals": vals[1],
                    "tu_sought": vals[2],
                    "pages": table.get("pages", []),
                    "needs_review": True,
                    "recovered": True,
                })
    return recovered


def extract_petition_summary_rows(petition_order_tables, pdf_path=None):
    """All rows of every petition table in PETITION_TABLES, each with its
    approval / actuals / claimed values (column names vary per table - see
    PETITION_TABLES). When `pdf_path` is given, also attempts
    recover_g8_tail() for tables with `recover: True`."""
    rows_out = []
    for t in petition_order_tables:
        title = t.get("title") or ""
        config = next((c for c in PETITION_TABLES if re.search(c["title_pattern"], title, re.I)), None)
        if config is None:
            continue
        header = t.get("header") or []
        unit = table_unit(t)
        table_rows = []
        for row in t.get("data_rows", []):
            label, label_idx, sl_no = find_label(row)
            if label is None:
                continue
            offset = table_offset(header, label_idx)
            table_rows.append({
                "field_label": label,
                "unit": unit,
                "table_no": t.get("table_no"),
                "arr_approval": find_column_value(header, row, config["approval_pat"], offset),
                "actuals": find_column_value(header, row, config["actuals_pat"], offset),
                "tu_sought": find_column_value(header, row, config["claimed_pat"], offset),
                "pages": t.get("pages", []),
                "needs_review": bool(t.get("needs_review")),
                "recovered": False,
            })
        if pdf_path and config["recover"]:
            found = {r["field_label"] for r in table_rows}
            table_rows.extend(recover_g8_tail(pdf_path, t, found))
        for r in table_rows:
            r["tuo_title_pattern"] = config["tuo_title_pattern"]
        rows_out.extend(table_rows)
    return rows_out


def match_schema_to_petition(schema_fields, petition_order_tables, pdf_path=None):
    """For each stage-1 schema field, find its petition-claimed figure
    from whichever table in PETITION_TABLES covers it. Only fields that
    legitimately appear in one of those tables get a match here - this
    mirrors stage (ii)'s ARR_FIELD_MAP scope deliberately, matching the
    same concepts the ARR side has already verified (see PETITION_TABLES
    and ARR_FIELD_MAP for what's covered so far). Fields outside that set
    are left unmatched, not guessed at. Pass `pdf_path` to also recover
    G8's tail rows when a page-break drops them - see recover_g8_tail.

    Matching is scoped by the schema field's own source table title
    against each petition row's `tuo_title_pattern` (set per PETITION_TABLES
    entry) - confirmed necessary, not just precautionary: TUO Table 2.9's
    "Sub total" (an unrelated per-project O&M rollup) was cross-matching
    against Table G10's "Sub Total" (interest charges) purely on label
    text before this scoping was added, silently attaching the wrong
    claimed value to an unrelated field."""
    petition_rows = extract_petition_summary_rows(petition_order_tables, pdf_path)
    petition_by_label = {}
    for r in petition_rows:
        petition_by_label.setdefault(_normalize(r["field_label"]), []).append(r)

    matched = []
    seen = set()
    for f in schema_fields:
        label = f["field_label"]
        if label in seen:
            continue
        candidates = petition_by_label.get(_normalize(label), [])
        hit = next((c for c in candidates if re.search(c["tuo_title_pattern"], f["table_title"] or "", re.I)), None)
        if hit is None:
            continue
        seen.add(label)
        matched.append({
            "field_label": label,
            "schema_table_no": f["table_no"],
            "unit": hit["unit"] or f["unit"],
            "petition_table_no": hit["table_no"],
            "arr_approval": hit["arr_approval"],
            "actuals": hit["actuals"],
            "claimed_value": hit["tu_sought"],
            "pages": hit["pages"],
            "needs_review": hit["needs_review"],
            "recovered": hit["recovered"],
        })
    return matched


if __name__ == "__main__":
    import json
    import sys

    from extract_sbu_g import extract_section
    from schema_discovery import discover_schema

    if len(sys.argv) < 3:
        print("Usage: python petition_claims.py <truing-up-order.pdf> <petition.pdf>")
        sys.exit(1)

    tuo_path, petition_path = sys.argv[1], sys.argv[2]

    tuo_result = extract_section(tuo_path)
    if "error" in tuo_result:
        print("Truing Up Order:", tuo_result["error"])
        sys.exit(1)
    schema_fields = discover_schema(tuo_result["order_tables"])

    petition_result = extract_section(petition_path)
    if "error" in petition_result:
        print("Petition:", petition_result["error"])
        sys.exit(1)

    claims = match_schema_to_petition(schema_fields, petition_result["order_tables"], petition_path)

    print(f"Schema fields: {len(schema_fields)}  | Matched to petition: {len(claims)}")
    print()
    for c in claims:
        print(f"  [{c['schema_table_no']}] {c['field_label']:<45} "
              f"ARR Approval={c['arr_approval']!s:<10} TU Sought(claimed)={c['claimed_value']}")

    with open("petition_claims_output.json", "w", encoding="utf-8") as fh:
        json.dump({"fields": claims}, fh, indent=2)
    print("\nWrote petition_claims_output.json")
