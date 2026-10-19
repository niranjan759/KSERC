"""Cost heads removed on the draft-order page are left out of the draft."""
from order_draft import _carried_paragraph, _fields_by_key, _table_rows, included, progress


def _field(label, excluded=False):
    return {"field_label": label, "arr_approved": "331.52", "petition_claimed": "336.46", "excluded": excluded}


def test_removed_heads_are_not_counted_or_drafted():
    fields = [_field("Depreciation", excluded=True), _field("Return on Equity (14%)")]
    assert [f["field_label"] for f in included(fields)] == ["Return on Equity (14%)"]
    assert progress(fields) == {"decided": 1, "total": 1, "removed": 1}


def test_removed_head_rows_are_dropped_from_order_tables():
    table = {"header": ["No", "Particulars", "MYT Order", "TU Sought", "KSERC Approval"],
             "data_rows": [["1", "Depreciation", "1", "2", "3"], ["2", "Return on Equity (14%)", "1", "2", "3"]]}
    fields = _fields_by_key({"fields": [_field("Depreciation", excluded=True), _field("Return on Equity (14%)")]})
    rows = _table_rows(table, fields)
    assert [r[1] for r in rows] == ["Return on Equity (14%)"]


def test_removed_head_decision_sentence_is_dropped():
    fields = _fields_by_key({"fields": [_field("Depreciation", excluded=True)]})
    text = "2.34 As above, the Commission hereby approves Depreciation of SBU-G of KSEB Ltd for the year 2023-24."
    assert _carried_paragraph(text, fields, "SBU-G", "2024-25") == []
