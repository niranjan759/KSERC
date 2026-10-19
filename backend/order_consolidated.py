"""Tables of the order that combine the three business units - Chapter 1's
summary (Table 1.1) and Chapter 7, "Consolidated Truing Up of KSEBL" - filled
from the three SBU comparisons of the same documents and year.

Each table is identified by its TITLE (never its number), and each of its
rows is listed with the compared items it adds up, so a row is only filled
when every one of its parts is known. Every mapping was checked against the
2023-24 order: the sums of the FY2023-24 comparisons equal the figures it
prints (e.g. Interest & Finance Charges claimed 2256.04 = SBU-G 155.96 +
SBU-T 462.22 + SBU-D 1637.86) - see tests/test_order_consolidated.py.
Where the order's own figure differs it is the order's source data, not the
mapping: its 1.1 "Amortization of intangible assets" MYT 14.94 is SBU-T's
Edamon-Kochi approval printed a row too high; its "Exceptional item" claim
15.40 is 15.56 in the three petitions."""
import re

from extraction.arr_budget import label_key
from extraction.compare import to_float

ROLE_PATS = [  # judged in this order: "Deviation from approval" is a difference
    ("myt", re.compile(r'MYT|ARR\s*&?\s*ERC|ARR\s*Approval', re.I)),
    ("difference", re.compile(r'Deviation|Difference', re.I)),
    ("actual", re.compile(r'Actual|audited|accounts', re.I)),
    ("approved", re.compile(r'KSERC|Approv', re.I)),
    ("claim", re.compile(r'petition|claim|sought|\bTU\b', re.I)),
]
SBU_ROW = re.compile(r'^SBU\s*-?\s*([GTD])\b', re.I)
TOTAL_ROW = re.compile(r'^Total$', re.I)
CELL_FIGURE = re.compile(r'^\(?[-+]?[\d,]*\.\d+\)?%?$|^\(?[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?$|^\d{4,}$')

G, T, D = "G", "T", "D"
# items made of one field per business unit
ITEMS = {
    "interest_finance": [(G, "Interest & Finance Charges"), (T, "Interest & Finance Charge"), (D, "Interest & Finance Charges")],
    "depreciation": [(G, "Depreciation"), (T, "Depreciation"), (D, "Depreciation")],
    "om": [(G, "O&M Expenses - Total"), (T, "O&M expenses"), (D, "Normative O&M Expenses")],
    "master_trust": [(G, "Additional contribution to Master Trust"), (T, "Additional contribution to Master Trust"),
                     (D, "Additional contribution to Master Trust")],
    "amortisation": [(G, "Amortisation of intangible assets"), (T, "Amortising of intangible assets"),
                     (D, "Amortisation of intangible assets")],
    "roe": [(G, "RoE"), (T, "Return on Equity (14%)"), (D, "Return on equity (14%)")],
    "exceptional": [(G, "Exceptional Items"), (T, "Exceptional items"), (D, "Exceptional items")],
    "repayment": [(G, "Repayment of master Trust Bond"), (T, "Repayment of existing master trust"), (D, "Repayment of Bonds")],
    "non_tariff": [(G, "Less Non-Tariff Income"), (T, "Less: Non-tariff Income"), (D, "Non-Tariff Income")],
    "mtb_interest": [(G, "Interest on Master Trust Bonds"), (T, "Interest on Master Trust Bonds"),
                     (D, "Interest on Master Trust Bond")],
}
# the KSEB-wide expenditure: the three units' ARR less what one unit charges
# another (SBU-D's cost of generation = SBU-G's ARR, its intra-state
# transmission = SBU-T's): 2023-24 666.69 + 1629.10 + 22005.88 - 626.48 -
# 1553.14 = 22122.05, as printed. New claim lines are inside the ARRs, so
# they are counted too.
NET_EXPENDITURE = [(G, "ARR", 1), (T, "ARR", 1), (D, "Total ARR", 1),
                   (D, "Cost of Generation (SBU-G)", -1), (D, "Cost of Intra-State Transmission (SBU-T)", -1)]
REVENUE_GAP = [(D, "Net Revenue Gap (-)/ Surplus (+)", 1)]

SUMMARY_ROWS = {  # Table 1.1 and Table 7.1
    "Generation Of Power": [(G, "Cost of Generation of Power")],
    "Purchase of power": [(D, "Cost of Power Purchase incl RLDC")],
    "Interest & Finance Charges": "interest_finance",
    "Depreciation": "depreciation",
    "O&M cost": "om",
    "Other Expenses": [(G, "Others"), (T, "Other expenses"), (D, "Other Expenses")],
    "Additional contribution to Master Trust": "master_trust",
    "Gains on T&D loss reduction": [(D, "Sharing of gains due to T&D loss")],
    "Edamon Kochi Compensation": [(T, "Edamon - Kochi line compensation")],
    "Thrissur Pugalur Compensation": [(T, "Pugalur – Thrissur line compensation")],
    "Incentive for excess Transmission target availability": [(T, "Incentive on Transmission Availability")],
    "Amortization of intangible assets- software": "amortisation",
    "Amortization of past gap": [(D, "Recovery of past gap")],
    "RoE": "roe",
    "Return on Equity": "roe",
    "Exceptional item": "exceptional",
    "Pay revision expenses": [(D, "Pay revision arrears")],
    "Repayment of bond": "repayment",
    "Net Expenditure (A)": NET_EXPENDITURE,
    "Non-Tariff Income": "non_tariff",
    # Total income = expenditure + gap (B - A = gap); revenue = that less
    # non-tariff income: 2023-24 22122.05 - 1323.75 - 1036.35 = 19761.95
    "Revenue from tariff & external sale": NET_EXPENDITURE + REVENUE_GAP +
        [(s, f, -1) for s, f in ITEMS["non_tariff"]],
    "Total Income (B)": NET_EXPENDITURE + REVENUE_GAP,
    "Revenue surplus /(Gap) (B-A)": REVENUE_GAP,
}

TABLES = [
    {   # Table 1.1 (Chapter 1) and Table 7.1 (Chapter 7)
        "title": r'Summary of the ARR, ERC and Revenue gap claimed for Truing up petition|'
                 r'Summary of the Audited Accounts and Truing up petition',
        "rows": SUMMARY_ROWS,
    },
    {   # Table 7.3 - its component rows can't be split by unit (SBU-D claims
        # Employee and A&G together), so only the total is filled
        "title": r'Summary of the O&M expenses claimed and approved',
        "rows": {"Total": "om"},
    },
    {   # Table 7.4
        "title": r'Interest and Finance charges claimed and approved for the year',
        "rows": {
            "Interest on outstanding loans": [(G, "Interest on Capital Liabilities"), (T, "Interest on Outstanding Capital"),
                                              (D, "Interest on outstanding Loans")],
            "Interest on security deposit": [(D, "Interest on Security Deposit")],
            "Master Trust Bond Interest": "mtb_interest",
            "Working capital/ OD interest": [(G, "Interest on Working capital"), (T, "Interest on Working capital"),
                                             (D, "Interest on working capital")],
            "PF interest": [(G, "Interest on GPF"), (T, "Interest on GPF"), (D, "Interest on GPF")],
            "Other interests": [(G, "Other Interests"), (T, "Other charges"), (D, "Other Interest")],
            "Carrying cost on past approved revenue gap": [(D, "Carrying cost on revenue gap till 2023-24")],
            "Total": "interest_finance",
        },
    },
    {   # Table 7.5: a row per business unit
        "title": r'Depreciation claimed and approved in the year',
        "by_sbu": "depreciation",
    },
    {   # Table 7.7: interest | approval | repayment | approval, a row per unit
        "title": r'Interest and repayment of principal to the bonds issued',
        "by_sbu": None,
        "columns": {1: ("mtb_interest", "claim"), 2: ("mtb_interest", "approved"),
                    3: ("repayment", "claim"), 4: ("repayment", "approved")},
    },
    {   # Table 7.8: equity amount (not a compared item) | RoE claimed | approved
        "title": r'Return on equity claimed and approved for',
        "by_sbu": None,
        "columns": {2: ("roe", "claim"), 3: ("roe", "approved")},
    },
    {   # Table 7.9: the units across, claimed / approved down
        "title": r'Non Tariff income approved for',
        "units_across": "non_tariff",
        "row_roles": {"Claimed for Truing Up": "claim", "Approved for Truing Up": "approved"},
    },
    # Tables 7.10 / 7.11 / 7.12 reprint each unit's own ARR summary: filled
    # from that unit's comparison exactly as in its own chapter
    {"title": r'ARR of the SBU-G Trued up', "unit": G},
    {"title": r'ARR of the SBU-T Trued up', "unit": T},
    {"title": r'ARR of the SBU-D Trued up', "unit": D},
]


def spec_for(table):
    title = table.get("title") or ""
    return next((s for s in TABLES if re.search(s["title"], title, re.I)), None)


def column_role(heading):
    for role, pat in ROLE_PATS:
        if pat.search(heading or ""):
            return role
    return None


def _field(units, sbu, label):
    comparison = units.get(sbu)
    if not comparison:
        return None
    want = label_key(label)
    return next((f for f in comparison.get("fields", []) if label_key(f["field_label"]) == want), None)


def _value(field, role, approved_of):
    """One compared item's figure for a column role, as a number; None when
    it isn't known. Nothing claimed (a blank in the petition) counts as 0;
    an item the ARR has no line for counts as 0 approved under the MYT
    order; an item removed from the order counts as 0."""
    if field.get("excluded"):
        return 0.0
    if role == "myt":
        return 0.0 if field.get("note") else to_float(field.get("arr_approved"))
    if role == "claim":
        v = to_float(field.get("petition_claimed"))
        return 0.0 if v is None else v
    if role == "actual":
        return to_float(field.get("petition_actuals"))
    if role == "approved":
        return to_float(approved_of(field))
    return None


def _total(units, parts, role, approved_of):
    """The signed sum of `parts` ([(sbu, field label[, sign])]) for a role,
    or None if any part's figure isn't known. "difference" is claim - MYT."""
    if role == "difference":
        claim, myt = _total(units, parts, "claim", approved_of), _total(units, parts, "myt", approved_of)
        return None if claim is None or myt is None else claim - myt
    total = 0.0
    for part in parts:
        sbu, label = part[0], part[1]
        sign = part[2] if len(part) > 2 else 1
        field = _field(units, sbu, label)
        value = _value(field, role, approved_of) if field is not None else None
        if value is None:
            return None
        total += sign * value
    return total


def _row_label(row):
    """The row's first cell that isn't a figure or a serial number. Not
    schema_discovery.find_label: that takes a short first cell for a serial
    number ("(a)", "II"), which would lose the row labelled "RoE"."""
    for cell in row:
        text = (cell or "").strip()
        if text and not CELL_FIGURE.match(text) and not re.fullmatch(r'\(?\d{1,2}\)?\.?|\(?[ivx]{1,4}\)\.?', text, re.I):
            return text
    return None


def _fmt(value):
    return "[[ ]]" if value is None else f"{value:.2f}"


def table_rows(table, units, approved_of, shift=lambda s: s, unit_rows=None):
    """The new order's cells for a consolidated table, in the extracted
    table's columns: compared figures where the row's parts are all known,
    a highlighted [ ] for any other figure, other text carried over.
    `units` is {"G"|"T"|"D": comparison}. None if the table isn't one of
    the consolidated tables. `unit_rows(table, sbu)` fills a reprinted unit
    summary (Tables 7.10-7.12) the way that unit's own chapter is filled."""
    spec = spec_for(table)
    if spec is None:
        return None
    if "unit" in spec:
        return unit_rows(table, spec["unit"]) if unit_rows else None

    header = table.get("header") or []
    roles = {j: column_role(h) for j, h in enumerate(header) if h}
    rows_spec = {label_key(k): v for k, v in (spec.get("rows") or {}).items()}
    out = []
    for row in table.get("data_rows", []):
        label = _row_label(row)
        values = {}  # column index -> figure
        if "units_across" in spec:
            role = next((r for k, r in spec["row_roles"].items() if label and label_key(k) == label_key(label)), None)
            if role:
                parts = ITEMS[spec["units_across"]]
                for j, h in enumerate(header):
                    m = SBU_ROW.match(h or "")
                    if m:
                        values[j] = _total(units, [p for p in parts if p[0] == m.group(1).upper()], role, approved_of)
                    elif TOTAL_ROW.match((h or "").strip()):
                        values[j] = _total(units, parts, role, approved_of)
        elif "by_sbu" in spec:
            m = SBU_ROW.match(label or "")
            pick = (lambda parts: [p for p in parts if p[0] == m.group(1).upper()]) if m else \
                (lambda parts: parts) if label and TOTAL_ROW.match(label.strip()) else None
            if pick:
                for j, h in enumerate(header):
                    if spec.get("columns"):
                        if j not in spec["columns"]:
                            continue
                        item, role = spec["columns"][j]
                    else:
                        item, role = spec["by_sbu"], roles.get(j)
                    if role:
                        values[j] = _total(units, pick(ITEMS[item]), role, approved_of)
        elif label:
            parts = rows_spec.get(label_key(label))
            if isinstance(parts, str):
                parts = ITEMS[parts]
            if parts:
                for j, role in roles.items():
                    if role:
                        values[j] = _total(units, parts, role, approved_of)

        cells = []
        label_at = next((j for j, c in enumerate(row) if label and (c or "").strip() == label), 0)
        for j, cell in enumerate(row):
            text = (cell or "").strip()
            if j in values:
                cells.append(_fmt(values[j]))
            elif CELL_FIGURE.match(text) or (j > label_at and is_number(text)):
                # any figure not filled from the comparisons is left blank -
                # never last year's number (Table 7.8's equity "831")
                cells.append("[[ ]]")
            else:
                cells.append(shift(text))
        out.append(cells)
    return out


NUMBER = re.compile(r'^\(?[-+]?(?:\d[\d,]*)(?:\.\d+)?\)?%?$')


def is_number(text):
    """A figure in a table cell, however short: "831", "1,811", "0.00"."""
    return bool(NUMBER.match((text or "").replace(" ", "")))
