"""Tables combining the three business units (Table 1.1, Chapter 7) are the
sums of the three SBU comparisons."""
import pytest

import order_consolidated as oc
import storage
from extraction.arr_budget import extract_arr_budget
from extraction.compare import build_comparison, to_float
from extraction.petition_claims import match_schema_to_petition, new_petition_lines
from extraction.schema_discovery import discover_schema


def _f(label, arr, claim, **kw):
    return {"field_label": label, "arr_approved": arr, "petition_claimed": claim, **kw}


UNITS = {
    "G": {"fields": [_f("Depreciation", "166.31", "159.67"), _f("RoE", "116.38", "116.38")]},
    "T": {"fields": [_f("Depreciation", "286.45", "309.17"), _f("Return on Equity (14%)", "119.99", "119.99")]},
    "D": {"fields": [_f("Depreciation", "285.00", "309.36"), _f("Return on equity (14%)", "253.50", "253.50")]},
}
CLAIM = lambda f: f.get("petition_claimed")  # approval = claim


def test_summary_rows_are_the_three_units_added_up():
    table = {"title": "Summary of the ARR, ERC and Revenue gap claimed for Truing up petition for SBU-D",
             "header": ["Particulars", "MYT order dated 25.06.2022", "Actual", "Sought for TU", "Deviation from approval"],
             "data_rows": [["Depreciation", "1", "2", "3", "4"], ["RoE", "1", "2", "3", "4"], ["Purchase of power", "1", "2", "3", "4"]]}
    rows = oc.table_rows(table, UNITS, CLAIM)
    assert rows[0] == ["Depreciation", "737.76", "[[ ]]", "778.20", "40.44"]   # no actuals given: left blank
    assert rows[1] == ["RoE", "489.87", "[[ ]]", "489.87", "0.00"]            # a three-letter label still read
    assert rows[2][1:] == ["[[ ]]"] * 4                                        # SBU-D's power purchase not given


def test_rows_by_business_unit_and_units_across():
    dep = {"title": "Depreciation claimed and approved in the year 2024-25",
           "header": ["SBUs", "ARR&ERC dated 25.06.2022", "As per the True Up petition", "Approved in the True up Order"],
           "data_rows": [["SBU-T", "1", "2", "3"], ["Total", "1", "2", "3"]]}
    assert oc.table_rows(dep, UNITS, CLAIM) == [["SBU-T", "286.45", "309.17", "309.17"],
                                               ["Total", "737.76", "778.20", "778.20"]]
    assert oc.table_rows({"title": "Something else", "header": [], "data_rows": []}, UNITS, CLAIM) is None


def test_last_years_figures_are_never_carried_over():
    # Table 7.8's equity amounts aren't compared items: blank, not last year's "831"
    roe = {"title": "Return on equity claimed and approved for 2024-25",
           "header": ["", "As per truing up petition Amount of Equity", "Return on Equity", "As approved Return on Equity"],
           "data_rows": [["SBU-G", "831", "116.38", "116.38"], ["Total", "3,499", "489.87", "489.87"]]}
    assert oc.table_rows(roe, UNITS, CLAIM) == [["SBU-G", "[[ ]]", "116.38", "116.38"],
                                               ["Total", "[[ ]]", "489.87", "489.87"]]


def _doc(doc_type, year=None):
    for d in storage.list_docs():
        if d.get("state") == "ready" and not d.get("updating") and d.get("doc_type") == doc_type \
                and (year is None or d.get("fiscal_year") == year):
            return d["doc_id"]
    return None


def test_2023_24_order_printed_figures_are_reproduced():
    """The FY2023-24 comparisons added up give the figures the 2023-24 order
    prints in Table 1.1 / 7.4 / 7.5 (checked here on the main rows; the
    order's own misprints are listed in order_consolidated's docstring)."""
    ids = (_doc("truing_up_order", "2023-24"), _doc("arr"), _doc("petition", "2023-24"))
    if not all(ids):
        pytest.skip("needs the uploaded documents (see test_comparison_baseline.py)")
    tuo_id, arr_id, pet_id = ids
    units = {}
    for sbu in "GTD":
        secs = {k: storage.section(storage.load_data(d), sbu) for k, d in (("t", tuo_id), ("a", arr_id), ("p", pet_id))}
        schema = discover_schema(secs["t"]["order_tables"])
        schema += new_petition_lines(schema, secs["p"]["order_tables"], sbu)
        units[sbu] = {"fields": build_comparison(
            extract_arr_budget(schema, secs["a"]["order_tables"], "2023-24", sbu),
            match_schema_to_petition(schema, secs["p"]["order_tables"], str(storage.pdf_path(pet_id)), sbu))}
    tables = {t["table_no"]: t for k in ("C1", "C7") for t in storage.section(storage.load_data(tuo_id), k)["order_tables"]}

    def filled(no):
        return {oc._row_label(r): r for r in oc.table_rows(tables[no], units, CLAIM)}

    t11 = filled("1.1")
    for label, myt, claim in [("Interest & Finance Charges", 2141.68, 2256.04), ("O&M cost", 4456.29, 4598.22),
                              ("Net Expenditure (A)", 20061.99, 22122.05), ("Non-Tariff Income", 866.94, 1036.35),
                              ("Revenue from tariff & external sale", 16255.96, 19761.95),
                              ("Revenue surplus /(Gap) (B-A)", -2939.09, -1323.75)]:
        assert abs(to_float(t11[label][1]) - myt) < 0.05 and abs(to_float(t11[label][3]) - claim) < 0.05, label
    assert abs(to_float(filled("7.4")["Total"][3]) - 2256.06) < 0.05
    assert abs(to_float(filled("7.5")["Total"][3]) - 778.20) < 0.05
