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
        # "provisional" too: ARR Table 5.42 (SBU-T) heads the Commission's
        # columns "KSERC provisional 2022-23 ..." with no word "approval"
        if c and re.search(r'approv|provisional', c, re.I):
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


# The ARR tables each mapping reads from, identified by TITLE, not number
# (finding #12): the 2022-27 ARR numbers these 4.22/4.23/4.30/4.53/4.60/4.63,
# but the next control period's ARR will number its tables differently -
# pinning the numbers would silently blank every approved value on a new
# ARR. Titles are the stable part, though a new ARR could still reword them;
# if approved values come back empty on a new ARR, check these first.
ARR_OM_SUMMARY = r'Summary of the O&M cost approved'
ARR_OM_COMPONENTS = r'Components\s*wise O&M expenses approved'
ARR_DEPRECIATION = r'Depreciation approved for the MYT period'
ARR_INTEREST_SUMMARY = r'Summary of Interest\s*&\s*Finance Charges'
ARR_CONTROL_PERIOD_SUMMARY = r'ARR of SBU-G for the control period as approved'
ARR_NET_SUMMARY = r'Net ARR for SBU-G as approved'


def find_row_in_table(order_tables, title_pattern, row_label):
    for t in order_tables:
        if not re.search(title_pattern, t.get("title") or "", re.I):
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
    ("O&M Expenses for existing stations", r'Transfer Cost of SBU-G', ARR_OM_SUMMARY,"Existing stations", None),
    ("O&M Expenses for new stations", r'Transfer Cost of SBU-G', ARR_OM_SUMMARY,"New Stations", None),
    ("O&M Expenses - Total", r'Transfer Cost of SBU-G', ARR_OM_SUMMARY,"Total", None),
    ("Interest & Finance Charges", r'Transfer Cost of SBU-G', ARR_INTEREST_SUMMARY,"Total Interest & Finance Charges", None),
    ("Depreciation", r'Transfer Cost of SBU-G', ARR_DEPRECIATION,"Total depreciation allowable during the year", None),
    ("Repayment of master Trust Bond", r'Transfer Cost of SBU-G', ARR_CONTROL_PERIOD_SUMMARY,"Repayment of master trust bond", None),
    ("Additional contribution to Master Trust", r'Transfer Cost of SBU-G', ARR_CONTROL_PERIOD_SUMMARY,"Additional contribution to master trust", None),
    ("Amortisation of intangible assets", r'Transfer Cost of SBU-G', None, None,
     "not budgeted as a separate ARR line; the Truing Up Order's own MYT-approved value is 0.00"),
    ("RoE", r'Transfer Cost of SBU-G', ARR_CONTROL_PERIOD_SUMMARY,"Return on Equity", None),
    ("Exceptional Items", r'Transfer Cost of SBU-G', None, None,
     "not budgeted as a separate ARR line; the Truing Up Order's own MYT-approved value is blank/0"),
    ("Others", r'Transfer Cost of SBU-G', None, None,
     "not budgeted as a separate ARR line; the Truing Up Order's own MYT-approved value is blank/0"),
    ("ARR", r'Transfer Cost of SBU-G', ARR_CONTROL_PERIOD_SUMMARY,"Aggregate Revenue Requirement", None),
    ("Less Non-Tariff Income", r'Transfer Cost of SBU-G', ARR_NET_SUMMARY,"Less Other Income", None),
    ("Net ARR (Transferred to SBU-D)", r'Transfer Cost of SBU-G', ARR_NET_SUMMARY,"Net ARR of SBU G", None),
    ("Employee Cost", r'O&M (expenses|cost) of SBU-G claimed', ARR_OM_COMPONENTS,"Employee expense", None),
    ("A&G Expenses", r'O&M (expenses|cost) of SBU-G claimed', ARR_OM_COMPONENTS,"A&G expenses", None),
    ("R&M Expenses", r'O&M (expenses|cost) of SBU-G claimed', ARR_OM_COMPONENTS,"R&M expenses", None),

    # Interest & Finance Charges sub-items (Table 2.12/2.14/2.15/2.18,
    # titled "Interest and finan[ce/cing] charges..." across the two
    # petition years' numbering) - source ARR Table 4.53, the same table
    # already used for the "Interest & Finance Charges" top-level total.
    # Verified: ARR 4.53's 2024-25 approval column for each of these rows
    # matches Petition G10's own "Approved" column exactly (e.g. Interest
    # on Capital Liabilities: 140.26 in both).
    ("Interest on Capital Liabilities", r'Interest and financ\w* charges', ARR_INTEREST_SUMMARY,"Interest on capital liabilities", None),
    ("Interest on GPF", r'Interest and financ\w* charges', ARR_INTEREST_SUMMARY,"Interest on GPF", None),
    ("Interest on Working capital", r'Interest and financ\w* charges', ARR_INTEREST_SUMMARY,"Interest on working capital", None),
    ("Interest on Master Trust Bonds", r'Interest and financ\w* charges', ARR_INTEREST_SUMMARY,"Interest on Bonds issued to Master Trust", None),
    ("Sub Total", r'Interest and financ\w* charges', ARR_INTEREST_SUMMARY,"Total Interest & Finance Charges", None),
    ("Other Interests", r'Interest and financ\w* charges', None, None,
     "not budgeted as a separate ARR line; the Truing Up Order's own MYT-approved value is 0.00"),
    ("Less: Capitalized", r'Interest and financ\w* charges', None, None,
     "not budgeted as a separate ARR line; the Truing Up Order's own MYT-approved value is 0.00"),
    ("Balance", r'Interest and financ\w* charges', None, None,
     "equals Sub Total less Capitalized - not a separate ARR-budgeted line"),
]


# --- SBU-T -------------------------------------------------------------
# Verified against the Truing Up Orders' own reprint of the MYT-approved
# figures, both years: ARR Table 5.51's approved column equals TUO Table
# 3.3's "MYT Order dated 25.06.2022" column (2023-24: Interest & Finance
# 431.23, RoE 119.99, Depreciation 286.45, O&M 644.81, Edamon-Kochi 14.94;
# 2024-25: 503.85 / 119.99 / 331.52 / 698.57 / 19.02). Two small
# discrepancies are in the SOURCE documents, not the extraction: the
# 2023-24 order reprints Repayment as 45.81 where the ARR says 45.79, and
# ARR / Net ARR as 1588.21 / 1533.35 against the ARR's 1588.20 / 1533.34.
# The ARR is the authority for approved figures.
# ARR figures are "SBU-T including SLDC" - so are the orders' SBU-T totals.
ARR_T_SUMMARY = r'KSERC approval-\s*ARR of SBU-T'
ARR_T_NET = r'KSERC approval-[\s-]*Net ARR of SBU-T'
ARR_T_OM_COMPONENTS = r'Components\s*wise O&M expenses of SBU-T'
ARR_T_INTEREST = r'Summary of Interest\s*&\s*Finance Charges of SBU-T'

TUO_T_SUMMARY = r'Expenses of SBU-T as per the True up petition|Approved Transfer Cost of SBU-T'
TUO_T_OM = r'Total O&M expenses of SBU-T'
TUO_T_INTEREST = r'Summary of the interest and finance charges of SBU-T'

_NOT_BUDGETED = "not budgeted as a separate ARR line; the Truing Up Order's own MYT-approved value is 0.00"

ARR_FIELD_MAP_T = [
    ("Interest & Finance Charge", TUO_T_SUMMARY, ARR_T_SUMMARY, "Interest and Finance Charges", None),
    ("Return on Equity (14%)", TUO_T_SUMMARY, ARR_T_SUMMARY, "Return on Equity", None),
    ("Depreciation", TUO_T_SUMMARY, ARR_T_SUMMARY, "Depreciation", None),
    ("O&M expenses", TUO_T_SUMMARY, ARR_T_SUMMARY, "O&M expenses", None),
    # worded differently in the 2023-24 and 2024-25 orders
    ("Repayment of existing master trust", TUO_T_SUMMARY, ARR_T_SUMMARY, "Repayment of existing master trust liability", None),
    ("Repayment of existing master trust bond", TUO_T_SUMMARY, ARR_T_SUMMARY, "Repayment of existing master trust liability", None),
    ("Additional contribution to Master Trust", TUO_T_SUMMARY, ARR_T_SUMMARY, "Additional contribution to Master Trust", None),
    ("Edamon - Kochi line compensation", TUO_T_SUMMARY, ARR_T_SUMMARY, "Edamon-Kochi line compensation", None),
    # the ARR has a row for it, but every year's cell is blank
    ("Pugalur - Thrissur line compensation", TUO_T_SUMMARY, None, None, _NOT_BUDGETED),
    ("Amortising of intangible assets", TUO_T_SUMMARY, None, None, _NOT_BUDGETED),
    ("Other expenses", TUO_T_SUMMARY, None, None, _NOT_BUDGETED),
    ("Refund of liquidated damages", TUO_T_SUMMARY, None, None, _NOT_BUDGETED),
    # the 2024-25 petition's wording; new that year, so it arrives as a new line
    ("Refunded liquidated damages", TUO_T_SUMMARY, None, None, _NOT_BUDGETED),
    ("Exceptional items", TUO_T_SUMMARY, None, None, _NOT_BUDGETED),
    ("Incentive on Transmission Availability", TUO_T_SUMMARY, None, None,
     "an incentive claimed at truing-up, not an ARR-budgeted cost; the Truing Up Order's own MYT-approved value is 0"),
    ("ARR", TUO_T_SUMMARY, ARR_T_SUMMARY, "Aggregate Revenue Requirement", None),
    ("Less: Non-tariff Income", TUO_T_SUMMARY, ARR_T_NET, "Non-tariff Income", None),
    # the label is cut short differently in each order's source table
    ("Net ARR (Cost Transferred to SBU-D)", TUO_T_SUMMARY, ARR_T_NET, "Net ARR", None),
    ("Net ARR (Cost Transferred to SBU-", TUO_T_SUMMARY, ARR_T_NET, "Net ARR", None),
    ("Net ARR (Cost Transferred to", TUO_T_SUMMARY, ARR_T_NET, "Net ARR", None),

    # O&M components: approved via ARR Table 5.11's component ratios
    ("Employee expenses", TUO_T_OM, ARR_T_OM_COMPONENTS, "Employee expense", None),
    ("A&G Expenses", TUO_T_OM, ARR_T_OM_COMPONENTS, "A&G expenses", None),
    ("R&M Expenses", TUO_T_OM, ARR_T_OM_COMPONENTS, "R&M expenses", None),

    # Interest & Finance Charges breakdown: ARR Table 5.42, whose approved
    # column matches the orders' MYT column exactly in both years (2023-24:
    # 316.61 / 26.50 / 64.13 / 23.99; 2024-25: 390.13 / 27.22 / 59.55 / 26.95)
    ("Interest on Outstanding Capital", TUO_T_INTEREST, ARR_T_INTEREST, "Interest on capital liabilities", None),
    ("Interest on Outstanding Capital Liabilities", TUO_T_INTEREST, ARR_T_INTEREST, "Interest on capital liabilities", None),
    ("Interest on GPF", TUO_T_INTEREST, ARR_T_INTEREST, "Interest on GPF", None),
    ("Interest on Master Trust Bonds", TUO_T_INTEREST, ARR_T_INTEREST, "Interest on Bonds issued to Master Trust", None),
    ("Interest on Working capital", TUO_T_INTEREST, ARR_T_INTEREST, "Interest on working capital", None),
    ("Other charges", TUO_T_INTEREST, None, None, _NOT_BUDGETED),
]

# SBU-D. Every approved value below was checked against the Truing Up
# Orders' own "MYT Order" column for 2023-24 and 2024-25. The ARR rounds a
# few totals a paisa differently (ARR 19996.32 vs the orders' 19996.33;
# Employee & A&G 3243.20 vs 3243.19) - the ARR is the authority.
ARR_D_SUMMARY = r'Summary of Approved ARR\s*&\s*ERC for the control period'
ARR_D_EMPLOYEE_AG = r'Employee cost and A&G expenses provisionally approved for the MYT'
ARR_D_OM = r'Summary of the O&M expenses provisionally approved for the MYT'
ARR_D_INTEREST = r'Summary of the interest and finance charges- claimed and approved for SBU-D'

# The 2023-24 order's Table 5.1 has three labels garbled by overlapping text
# ("cChoasrtg oefs I ntra-State Transmission"), so those fields are picked
# up from its later ARR table (5.90) / revenue gap table (5.94) instead,
# which print the same rows cleanly.
TUO_D_SUMMARY = (r'ARR, ERC and Revenue gap of SBU-D|Aggregate Revenue Requirement for the purpose of Truing up of SBU-D'
                 r'|Revenue gap approved for SBU-D')
TUO_D_OM = r'Summary of the expenses claimed by KSEB Ltd'
TUO_D_INTEREST = r'Summary of the interest and finance charges of SBU-D|KSEB petition- Interest and financing charges claimed'

_INCENTIVE = "an incentive claimed at truing-up, not an ARR-budgeted cost; the Truing Up Order's own MYT-approved value is 0.00"

ARR_FIELD_MAP_D = [
    ("Cost of Generation (SBU-G)", TUO_D_SUMMARY, ARR_D_SUMMARY, "Cost of Generation", None),
    # cut short in the 2023-24 order's Table 5.1
    ("Cost of Power Purchase incl RLDC", TUO_D_SUMMARY, ARR_D_SUMMARY, "Cost of Power Purchase", None),
    ("Cost of Power Purchase incl RLDC charges", TUO_D_SUMMARY, ARR_D_SUMMARY, "Cost of Power Purchase", None),
    ("Cost of Intra-State Transmission (SBU-T)", TUO_D_SUMMARY, ARR_D_SUMMARY, "Cost of Intra State Transmission", None),
    ("Interest & Finance Charges", TUO_D_SUMMARY, ARR_D_SUMMARY, "I&F charges", None),
    ("Additional contribution to Master Trust", TUO_D_SUMMARY, ARR_D_SUMMARY, "Additional contribution to Master Trust", None),
    ("Depreciation", TUO_D_SUMMARY, ARR_D_SUMMARY, "Depreciation", None),
    ("Normative O&M Expenses", TUO_D_SUMMARY, ARR_D_SUMMARY, "O&M Expenses", None),
    ("Return on equity (14%)", TUO_D_SUMMARY, ARR_D_SUMMARY, "Return on Equity", None),
    ("Recovery of past gap", TUO_D_SUMMARY, ARR_D_SUMMARY, "Recovery of previous gap", None),
    ("Repayment of Bonds", TUO_D_SUMMARY, ARR_D_SUMMARY, "Repayment of Bond", None),
    ("Pay revision arrears", TUO_D_SUMMARY, None, None, _NOT_BUDGETED),
    ("Other Expenses", TUO_D_SUMMARY, None, None, _NOT_BUDGETED),
    ("Exceptional items", TUO_D_SUMMARY, None, None, _NOT_BUDGETED),
    # also printed "... T&D loss reduction" (Table 5.90); one field, one entry
    ("Sharing of gains due to T&D loss", TUO_D_SUMMARY, None, None, _INCENTIVE),
    ("Amortisation of intangible assets", TUO_D_SUMMARY, None, None, _NOT_BUDGETED),
    ("Registration charges for solar refunded", TUO_D_SUMMARY, None, None, _NOT_BUDGETED),
    ("Refund of liquidated damages", TUO_D_SUMMARY, None, None, _NOT_BUDGETED),
    ("Total ARR", TUO_D_SUMMARY, ARR_D_SUMMARY, "Aggregate Revenue Requirement", None),
    ("Non-Tariff Income", TUO_D_SUMMARY, ARR_D_SUMMARY, "Less Nontariff Income", None),
    ("Less Non Tariff Income", TUO_D_SUMMARY, ARR_D_SUMMARY, "Less Nontariff Income", None),
    ("Net ARR", TUO_D_SUMMARY, ARR_D_SUMMARY, "Net ARR", None),
    ("Revenue from external sale", TUO_D_SUMMARY, ARR_D_SUMMARY, "Revenue from sale of surplus power", None),
    # The ARR states the gap as a positive shortfall (2939.09); the petition
    # and orders print it as a negative "Net Revenue Gap (-)/ Surplus (+)"
    # (-2939.12). Negated so both read in the petition's convention.
    ("Net Revenue Gap (-)/ Surplus (+)", TUO_D_SUMMARY, ARR_D_SUMMARY, "Revenue gap", None, {"negate": True}),
    # Tariff income, power factor incentive and Total ERC are left out: the
    # ARR budgets tariff revenue only NET of the power factor incentive
    # (15873.80 = 15903.34 - 29.54), so neither line compares one-to-one.

    # O&M components. The ARR's R&M figure sits in a table that lists years
    # down the rows, KSEB Ltd's and KSERC's figures side by side across.
    ("Employee Cost & A&G Expenses", TUO_D_OM, ARR_D_EMPLOYEE_AG, "Employee cost and A&G Cost (Rs Cr)", None),
    ("R&M Expenses", TUO_D_OM, ARR_D_OM, "R&M expenses", None, {"year_rows": True}),

    # Interest & Finance Charges breakdown (ARR Table 6.158's KSERC half)
    ("Interest on outstanding Loans", TUO_D_INTEREST, ARR_D_INTEREST, "Interest on capital liabilities", None),
    ("Interest on Term Loans", TUO_D_INTEREST, ARR_D_INTEREST, "Interest on capital liabilities", None),
    ("Interest on Security Deposit", TUO_D_INTEREST, ARR_D_INTEREST, "Interest on security Deposit", None),
    ("Interest on GPF", TUO_D_INTEREST, ARR_D_INTEREST, "Interest on GPF", None),
    ("Interest on Master Trust Bond", TUO_D_INTEREST, ARR_D_INTEREST, "Interest on MT Bonds", None),
    # the label ends in a year ("... till 2023-24"), compared without it
    ("Carrying cost on revenue gap till", TUO_D_INTEREST, ARR_D_INTEREST, "Carrying cost", None),
    ("Interest on working capital", TUO_D_INTEREST, ARR_D_INTEREST, "Interest on working capital", None),
    ("Other Interest", TUO_D_INTEREST, None, None, _NOT_BUDGETED),
]

# One verified map per SBU. An SBU is only offered for comparison once it
# has an entry here AND in petition_claims.PETITION_TABLES_BY_SBU.
ARR_FIELD_MAPS = {"G": ARR_FIELD_MAP, "T": ARR_FIELD_MAP_T, "D": ARR_FIELD_MAP_D}

TRAILING_YEAR_PAT = re.compile(r'\s*\d{4}\s*-\s*\d{2,4}\s*$')


def label_key(label):
    """A row label for matching across documents: normalized, and without a
    trailing year - SBU-D's "Carrying cost on revenue gap till 2023-24"
    names the year it's claimed for, so its wording changes every year."""
    return _normalize(TRAILING_YEAR_PAT.sub("", label or ""))


def _lookup_map(field_label, schema_table_title, field_map):
    # compared normalized: extracted labels carry odd dash / quote glyphs
    # ("Pugalur – Thrissur"), which exact comparison would trip on
    want = label_key(field_label)
    for position, entry in enumerate(field_map):
        entry_label, title_pattern, arr_table_no, arr_row_label, note = entry[:5]
        opts = entry[5] if len(entry) > 5 else {}
        if label_key(entry_label) == want and re.search(title_pattern, schema_table_title or "", re.I):
            return arr_table_no, arr_row_label, note, opts, position
    return None


def find_year_rows_column(order_tables, title_pattern, column_label):
    """For a table that lists years down its rows (ARR Table 6.124: one row
    per year, "KSEB Ltd petition ... | KSERC provisional ..." across), the
    {year: value} of the column named `column_label` in the Commission's
    half of the header."""
    for t in order_tables:
        if not re.search(title_pattern, t.get("title") or "", re.I):
            continue
        header = t.get("header") or []
        start = next((i for i, c in enumerate(header) if c and re.search(r'approv|provisional', c, re.I)), 0)
        col = next((i for i in range(start, len(header))
                    if header[i] and _normalize(column_label) in _normalize(header[i])), None)
        if col is None:
            continue
        by_year = {}
        for row in t.get("data_rows", []):
            yk = _year_key(row[0]) if row and row[0] else None
            if yk and col < len(row):
                by_year[yk] = row[col]
        if by_year:
            return t, by_year
    return None


def _negated(v):
    if v in (None, ""):
        return v
    try:
        n = -float(str(v).replace(",", ""))
    except ValueError:
        return v
    return f"{n:.2f}"


def extract_arr_budget(schema_fields, arr_order_tables, target_year, sbu="G"):
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
    position_of = {}
    for f in schema_fields:
        label = f["field_label"]
        if label in seen:
            continue
        entry = _lookup_map(label, f["table_title"], ARR_FIELD_MAPS[sbu])
        if entry is None:
            continue
        seen.add(label)
        arr_table_pattern, arr_row_label, note, opts, position_of[label] = entry
        # two schema labels reading the same ARR row are one item under
        # two wordings (the 2023-24 order cuts "Net ARR (Cost Transferred to
        # SBU-D)" short differently in two tables; SBU-G's interest "Sub
        # Total" repeats "Interest & Finance Charges") - keep the first
        target = (arr_table_pattern, _normalize(arr_row_label)) if arr_table_pattern else ("label", _normalize(label))
        if target in seen:
            continue
        seen.add(target)

        if arr_table_pattern is None:
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
                "new_in_petition": bool(f.get("new_in_petition")),
            })
            continue

        year_rows = None
        if opts.get("year_rows"):
            year_rows = find_year_rows_column(arr_order_tables, arr_table_pattern, arr_row_label)
            found = (year_rows[0], None, None, None) if year_rows else None
        else:
            found = find_row_in_table(arr_order_tables, arr_table_pattern, arr_row_label)
        if found is None:
            # Deliberately NOT a `note`: a note means "confirmed, the ARR
            # budgets nothing here", and the dashboard renders it that way.
            # A row we expected but couldn't find (e.g. a new ARR that
            # rewords a table title) must show up as needing review, or a
            # layout change would pass for a legitimate zero.
            results.append({
                "field_label": label,
                "schema_table_no": f["table_no"],
                "arr_table_no": None,
                "arr_row_label": arr_row_label,
                "unit": f["unit"],
                "approved_value": None,
                "approved_by_year": {},
                "pages": [],
                "needs_review": True,
                "note": None,
                "lookup_problem": f"Expected ARR row '{arr_row_label}' not found - the ARR's layout may differ",
                "new_in_petition": bool(f.get("new_in_petition")),
            })
            continue

        t, row, header, label_idx = found
        by_year = year_rows[1] if year_rows else _approved_year_values(header, row, label_idx)
        if opts.get("negate"):
            by_year = {y: _negated(v) for y, v in by_year.items()}
        missing_year = target_year not in by_year
        results.append({
            "field_label": label,
            "schema_table_no": f["table_no"],
            "arr_table_no": t.get("table_no"),
            "arr_row_label": arr_row_label,
            "unit": f["unit"] or table_unit(t),
            "approved_value": by_year.get(target_year),
            "approved_by_year": by_year,
            "pages": t.get("pages", []),
            "needs_review": bool(t.get("needs_review")) or missing_year,
            "note": note,
            "lookup_problem": (f"ARR table {t.get('table_no')} has no {target_year} column" if missing_year else None),
            "new_in_petition": bool(f.get("new_in_petition")),
        })
    # in the map's order, which follows the orders' own summary tables -
    # not the schema's, which files SBU-D's cleanly printed summary lines
    # after all of its breakdown tables
    results.sort(key=lambda r: position_of[r["field_label"]])
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
