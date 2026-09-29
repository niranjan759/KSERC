import re
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))

from arr_budget import label_key
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
        "report_new_lines": True,
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
    {
        # "Details of O&M expenses for <year> (Rs Cr)" - the O&M
        # Employee/A&G/R&M split. Its "TU requirement" column is BLANK for
        # all three components in both petition years (confirmed against
        # the raw PDF text, not an extraction loss): KSEB claims O&M on a
        # normative basis as a single total, so there is no per-component
        # claim to compare. Wired in anyway so these rows link to their
        # source page and say so explicitly, instead of showing an
        # unexplained blank. Its "Total" row is excluded via only_labels -
        # it duplicates "O&M Expenses - Total", already compared from G8.
        "title_pattern": r'Details of O&M expenses',
        "tuo_title_pattern": r'O&M (expenses|cost) of SBU-G claimed',
        "approval_pat": r'Approved',
        "actuals_pat": r'Actual',
        # word boundaries matter: a bare case-insensitive r'TU' matches
        # inside "AcTUal" (the column before it) and silently reads the
        # Actuals figure as the claim - confirmed, it produced a +2452%
        # "deviation" on A&G Expenses before this was fixed.
        "claimed_pat": r'\bTU\b',
        "recover": False,
        "only_labels": ["Employee Cost", "A&G Expenses", "R&M Expenses"],
        "blank_claim_note": "No separate claim in the petition - O&M is claimed only as a total (see O&M Expenses - Total)",
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


def _shifted_index(header, table_rows, idx):
    """Where a named column's values actually sit. In Petition 2024-25
    Table T6 every "Truing up requirement" value lands one column LEFT of
    that header, under a blank-header column, while the named column itself
    is empty in every single row. Judged across the whole table, never per
    row: a column that's empty for just some rows is ordinary (Table G13's
    claim column is blank for its components but filled on its Total row),
    and treating that as a shift would read the neighbouring "Actual"
    figures as the claim."""
    # idx can run off the header: a wrapped remark ("See Form" / "D 3.4")
    # read as a row label gives that row a large negative offset
    if not 1 <= idx <= len(header) or header[idx - 1] not in (None, ""):
        return idx
    own = [r[idx] for r in table_rows if idx < len(r)]
    left = [r[idx - 1] for r in table_rows if idx - 1 < len(r)]
    if own and all(v in (None, "") for v in own) and sum(v not in (None, "") for v in left) >= len(left) / 2:
        return idx - 1
    return idx


def _row_shifted_index(header, row, idx):
    """One row whose values sit a column left of everyone else's. In the
    petitions' SBU-D summary (D76 / D89) the two-line "Sharing of gains on
    account of higher T&D loss reduction" row puts each value under the
    blank-header column to the left, and has NO cell at all (None, not an
    empty string) where the named column is. Only that exact shape counts:
    a real but empty cell ("") is an ordinary blank value, and a named
    column to the left is a different figure, never a shifted one."""
    if 1 <= idx < len(row) and idx <= len(header) and row[idx] is None and header[idx - 1] in (None, "") \
            and NUM_TOKEN_PAT.match(str(row[idx - 1] or "").strip()):
        return idx - 1
    return idx


def find_column_value(header, row, column_pattern, offset=0, table_rows=None):
    row = _realign_row(header, row)
    for i, h in enumerate(header):
        if h and re.search(column_pattern, h, re.I):
            idx = i - offset
            # after the offset correction, not before: a table with a
            # whole-table offset (finding #14, Petition 2023-24 G10) would
            # otherwise be corrected twice and read an empty column
            if table_rows is not None:
                idx = _shifted_index(header, table_rows, idx)
            idx = _row_shifted_index(header, row, idx)
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


PETITION_TABLES_T = [
    {
        # "ARR OF TRANSMISSION BUSINESS UNIT (SBU-T) & SLDC for <year>" -
        # Table T8 (2023-24) / T6 (2024-25). Row labels match the orders'
        # Table 3.3 apart from the aliases in PETITION_ALIASES_BY_SBU["T"].
        "title_pattern": r'ARR OF TRANSMISSION BUSINESS UNIT',
        "tuo_title_pattern": r'Expenses of SBU-T as per the True up petition|Approved Transfer Cost of SBU-T',
        "approval_pat": r'^Approved$',
        "actuals_pat": r'^Actual$',
        "claimed_pat": r'Truing up requirement',
        "recover": False,
        "report_new_lines": True,
    },
    {
        # "Summary of Interest and Finance charges (Rs Cr)" - Table T12 / T10
        "title_pattern": r'Summary of Interest and Finance charges',
        "tuo_title_pattern": r'Summary of the interest and finance charges of SBU-T',
        "approval_pat": r'^Approved$',
        "actuals_pat": r'Accounts',
        "claimed_pat": r'True-up requirement',
        "recover": False,
    },
]

_TUO_D_SUMMARY = (r'ARR, ERC and Revenue gap of SBU-D|Aggregate Revenue Requirement for the purpose of Truing up of SBU-D'
                  r'|Revenue gap approved for SBU-D')

PETITION_TABLES_D = [
    {
        # "ARR & ERC OF DISTRIBUTION BUSINESS UNIT (Rs Cr)" - Table D76
        # (2023-24) / D89 (2024-25), the orders' Table 5.1 reprinted
        "title_pattern": r'ARR & ERC OF DISTRIBUTION BUSINESS UNIT',
        "tuo_title_pattern": _TUO_D_SUMMARY,
        "approval_pat": r'^Approved$',
        "actuals_pat": r'^Actuals?$',
        "claimed_pat": r'^True up$',
        "recover": False,
        "report_new_lines": True,
    },
    {
        # "Components of O&M Expenses for SBU D (Rs Cr)" - Table D75
        # (2024-25). The 2023-24 petition's D63 of the same title gives only
        # the O&M total, so its components come back blank.
        "title_pattern": r'Components of O&M Expenses for SBU D',
        "tuo_title_pattern": r'Summary of the expenses claimed by KSEB Ltd',
        "approval_pat": r'^Approved$',
        "actuals_pat": r'As per accounts',
        "claimed_pat": r'True up claim',
        "recover": False,
    },
    {
        # "Comparison of I&FC for <year> (Rs. Cr)" - Table D65 / D77. Not the
        # 2023-24 petition's D71, which splits the carrying cost in two.
        "title_pattern": r'Comparison of I\s*&\s*FC for',
        "tuo_title_pattern": r'Summary of the interest and finance charges of SBU-D|KSEB petition- Interest and financing charges claimed',
        "approval_pat": r'^Approved$',
        "actuals_pat": r'Accounts',
        "claimed_pat": r'True up claim',
        "recover": False,
    },
]

PETITION_TABLES_BY_SBU = {"G": PETITION_TABLES, "T": PETITION_TABLES_T, "D": PETITION_TABLES_D}

# Labels that name the same item in different documents / years. Unlike
# SBU-G, SBU-T's petition and order wording diverge in a few places, and
# some labels are cut short in the source tables. Each group was checked
# against the figures, not assumed from the wording.
PETITION_ALIASES_BY_SBU = {
    "T": [
        ["Repayment of existing master trust", "Repayment of existing master trust bond",
         "Repayment of bond to master trust"],
        ["Net ARR (Cost Transferred to SBU-D)", "Net ARR (Cost Transferred to SBU-",
         "Net ARR (Cost Transferred to"],
        ["Interest on Outstanding Capital", "Interest on Outstanding Capital Liabilities"],
        ["Refund of liquidated damages", "Refunded liquidated damages"],
    ],
    "D": [
        ["Cost of Power Purchase incl RLDC", "Cost of Power Purchase incl RLDC charges"],
        ["Sharing of gains due to T&D loss", "Sharing of gains due to T&D loss reduction",
         "Sharing of gains on account of higher T&D loss",
         "Sharing of gains on account of higher T&D loss reduction"],
        ["Non-Tariff Income", "Less Non Tariff Income"],
        # the 2024-25 order's name for the same line
        ["Interest on outstanding Loans", "Interest on Term Loans"],
    ],
}

# Items the petition deliberately doesn't claim separately. SBU-T's O&M is
# claimed only as a normative total: the Truing Up Order's own "As per
# True-up petition" column for Employee / A&G / R&M literally reads "(Total
# O&M expenses as per norms)", and the petition has no component table.
NO_SEPARATE_CLAIM_BY_SBU = {
    "T": [{
        "tuo_title_pattern": r'Total O&M expenses of SBU-T',
        "labels": ["Employee expenses", "A&G Expenses", "R&M Expenses"],
        "note": "No separate claim in the petition - O&M is claimed only as a normative total (see O&M expenses)",
    }],
    # SBU-D's petition summary stops at Total ARR and lists Non-Tariff
    # Income among the revenue lines; it never states a Net ARR.
    "D": [{
        "tuo_title_pattern": _TUO_D_SUMMARY,
        "labels": ["Net ARR"],
        "note": "No separate claim in the petition - it states Total ARR and Non-Tariff Income, not their difference",
    }],
}


def extract_petition_summary_rows(petition_order_tables, pdf_path=None, sbu="G"):
    """All rows of every petition table in PETITION_TABLES, each with its
    approval / actuals / claimed values (column names vary per table - see
    PETITION_TABLES). When `pdf_path` is given, also attempts
    recover_g8_tail() for tables with `recover: True`."""
    rows_out = []
    for t in petition_order_tables:
        title = t.get("title") or ""
        config = next((c for c in PETITION_TABLES_BY_SBU[sbu] if re.search(c["title_pattern"], title, re.I)), None)
        if config is None:
            continue
        header = t.get("header") or []
        unit = table_unit(t)
        only = {_normalize(l) for l in config.get("only_labels", [])}
        table_rows = []
        for row in t.get("data_rows", []):
            label, label_idx, sl_no = find_label(row)
            if label is None:
                continue
            if only and _normalize(label) not in only:
                continue
            offset = table_offset(header, label_idx)
            data = t.get("data_rows", [])
            claimed = find_column_value(header, row, config["claimed_pat"], offset, data)
            table_rows.append({
                "field_label": label,
                "unit": unit,
                "table_no": t.get("table_no"),
                "arr_approval": find_column_value(header, row, config["approval_pat"], offset, data),
                "actuals": find_column_value(header, row, config["actuals_pat"], offset, data),
                "tu_sought": claimed,
                "claim_note": config.get("blank_claim_note") if claimed in (None, "") else None,
                "pages": t.get("pages", []),
                "needs_review": bool(t.get("needs_review")),
                "recovered": False,
            })
        if pdf_path and config["recover"]:
            found = {r["field_label"] for r in table_rows}
            table_rows.extend(recover_g8_tail(pdf_path, t, found))
        for r in table_rows:
            r["tuo_title_pattern"] = config["tuo_title_pattern"]
            r["report_new_lines"] = bool(config.get("report_new_lines"))
        rows_out.extend(table_rows)
    return rows_out


def match_schema_to_petition(schema_fields, petition_order_tables, pdf_path=None, sbu="G"):
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
    petition_rows = extract_petition_summary_rows(petition_order_tables, pdf_path, sbu)
    petition_by_label = {}
    for r in petition_rows:
        petition_by_label.setdefault(label_key(r["field_label"]), []).append(r)

    alias_of = {}
    for group in PETITION_ALIASES_BY_SBU.get(sbu, []):
        for name in group:
            alias_of[label_key(name)] = [label_key(n) for n in group]
    no_claims = NO_SEPARATE_CLAIM_BY_SBU.get(sbu, [])

    matched = []
    seen = set()
    for f in schema_fields:
        label = f["field_label"]
        if label in seen:
            continue
        names = alias_of.get(label_key(label), [label_key(label)])
        candidates = [c for n in names for c in petition_by_label.get(n, [])]
        hit = next((c for c in candidates if re.search(c["tuo_title_pattern"], f["table_title"] or "", re.I)), None)
        no_claim = next((nc for nc in no_claims
                         if re.search(nc["tuo_title_pattern"], f["table_title"] or "", re.I)
                         and label_key(label) in {label_key(l) for l in nc["labels"]}), None)
        if hit is None and no_claim:
            seen.add(label)
            matched.append({
                "field_label": label, "schema_table_no": f["table_no"], "unit": f["unit"],
                "petition_table_no": None, "arr_approval": None, "actuals": None, "claimed_value": None,
                "pages": [], "needs_review": False, "recovered": False, "claim_note": no_claim["note"],
                "new_in_petition": bool(f.get("new_in_petition")),
            })
            continue
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
            "claim_note": hit.get("claim_note"),
            "new_in_petition": bool(f.get("new_in_petition")),
        })
    return matched


def new_petition_lines(schema_fields, petition_order_tables, sbu="G"):
    """Claim lines in this year's petition that last year's Truing Up Order
    has no row for. The schema is learned from last year's order, so a head
    of expense that's new this year would otherwise never be compared -
    e.g. the 2024-25 petition's SBU-D "Registration charges for solar
    refunded" (24.18) and "Refund of liquidated damages" (16.30), neither
    of which is in the 2023-24 order. Only the per-SBU summary tables
    (PETITION_TABLES entries with `report_new_lines`) are checked: every
    claim reaches the summary, and the detail tables carry too many
    sub-rows and wrapped-label fragments to report usefully.

    A line whose claimed amount is already matched to a schema field isn't
    new: SBU-T's petition summary repeats the interest breakdown ("Interest
    on loan" 409.93) that the order keeps in a separate interest table
    under other names ("Interest on Outstanding Capital" 409.93).

    Returns stand-in schema fields (flagged `new_in_petition`) filed under
    the order's summary table, so the ARR map and the petition match treat
    them like any other field."""
    from compare import to_float

    rows = [r for r in extract_petition_summary_rows(petition_order_tables, None, sbu) if r["report_new_lines"]]
    alias_of = {}
    for group in PETITION_ALIASES_BY_SBU.get(sbu, []):
        for name in group:
            alias_of[label_key(name)] = {label_key(n) for n in group}
    already_claimed = {to_float(m["claimed_value"])
                       for m in match_schema_to_petition(schema_fields, petition_order_tables, None, sbu)}

    out = []
    seen = set()
    for r in rows:
        claimed = to_float(r["tu_sought"])
        # a wrapped label's second line ("reduction") has no value of its own
        if claimed is None or (claimed != 0 and claimed in already_claimed):
            continue
        scope = [f for f in schema_fields if re.search(r["tuo_title_pattern"], f["table_title"] or "", re.I)]
        if not scope:
            continue
        key = label_key(r["field_label"])
        names = alias_of.get(key, {key})
        if key in seen or any(label_key(f["field_label"]) in names for f in scope):
            continue
        seen.add(key)
        out.append({
            "table_no": None,
            "table_title": scope[0]["table_title"],
            "sl_no": None,
            "field_label": r["field_label"],
            "unit": r["unit"] or scope[0]["unit"],
            "new_in_petition": True,
        })
    return out


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
