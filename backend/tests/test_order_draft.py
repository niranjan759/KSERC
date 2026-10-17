import io
import docx

import order_draft


def field(**kw):
    base = {"field_label": "Depreciation", "unit": "Rs. Cr", "arr_approved": "175.00", "petition_claimed": "182.74"}
    base.update(kw)
    return base


def test_pending_field_has_no_approved_figure():
    assert order_draft.effective_approved(field(decision="pending")) is None


def test_accepting_takes_the_claim_and_follows_later_edits_to_it():
    f = field()
    order_draft.apply_decision(f, {"decision": "accepted"})
    assert order_draft.effective_approved(f) == "182.74"
    f["petition_claimed"] = "180.00"
    assert order_draft.effective_approved(f) == "180.00"


def test_typing_a_figure_equal_to_the_claim_means_accepted_otherwise_modified():
    f = field()
    order_draft.apply_decision(f, {"commission_approved": "182.74"})
    assert f["decision"] == "accepted"
    order_draft.apply_decision(f, {"commission_approved": "170.00"})
    assert (f["decision"], order_draft.effective_approved(f)) == ("modified", "170.00")
    order_draft.apply_decision(f, {"commission_approved": ""})
    assert f["decision"] == "pending"


def test_disallowed_approves_nothing_and_unknown_decision_is_refused():
    f = field()
    order_draft.apply_decision(f, {"decision": "disallowed"})
    assert order_draft.effective_approved(f) == "0.00"
    try:
        order_draft.apply_decision(f, {"decision": "maybe"})
    except ValueError:
        return
    raise AssertionError("unknown decision accepted")


def test_draft_states_decisions_and_leaves_pending_items_as_placeholders(monkeypatch):
    monkeypatch.setattr(order_draft, "_template_facts", lambda data: ("2", "25.06.2022"))
    decided = field(decision="modified", commission_approved="170.00", reason="Normative basis applied.")
    pending = field(field_label="RoE", arr_approved="116.38", petition_claimed="116.38", decision="pending")
    data = {"sbu": "G", "target_year": "2024-25", "fields": [decided, pending]}
    document = docx.Document(io.BytesIO(order_draft.build_docx(data)))
    text = "\n".join(p.text for p in document.paragraphs)
    assert "at Rs. 170.00 Cr as against Rs. 182.74 Cr claimed by KSEB Ltd" in text
    assert "Normative basis applied." in text
    assert "[Commission's decision on RoE is pending" in text


def test_a_field_with_a_claim_defaults_to_accepted_and_one_without_stays_pending():
    assert order_draft.decision_of(field()) == "accepted"
    assert order_draft.effective_approved(field()) == "182.74"
    assert order_draft.decision_of(field(petition_claimed=None)) == "pending"
    assert order_draft.decision_of(field(decision="pending")) == "pending"


def test_financial_years_and_year_end_dates_move_on_but_other_years_stay():
    assert order_draft.shift_year("for the year 2023-24 as on 31.03.2024") == "for the year 2024-25 as on 31.03.2025"
    assert order_draft.shift_year("Tariff Regulations, 2021 and the Act, 2003") == "Tariff Regulations, 2021 and the Act, 2003"
    assert order_draft.shift_year("FY 2022 – 23 and 2099-00") == "FY 2023 – 24 and 2100-01"


def test_carried_figures_are_highlighted_but_the_clause_number_is_not():
    marked = order_draft._mark_figures("2.5 KSEB Ltd submitted 5721.17 MU against 7,235.74 MU on 25.06.2022 under Section 131.")
    assert marked.startswith("2.5 KSEB Ltd")
    assert "{{5721.17}}" in marked and "{{7,235.74}}" in marked and "{{25.06.2022}}" in marked
    assert "{{131}}" not in marked


def test_sentences_broken_at_a_hyphen_or_after_rs_are_joined_back():
    blocks = [{"type": "heading", "text": "As above, the Commission hereby approves the O&M expenses of SBU-"},
              {"type": "para", "text": "G of KSEB Ltd for the year 2023-24 at Rs. 186.16 Cr as against Rs."},
              {"type": "para", "text": "189.46 Cr claimed by KSEB Ltd."},
              {"type": "para", "text": "2.35 Next clause."}]
    joined = order_draft._join_hyphen_breaks(blocks)
    assert len(joined) == 2
    assert joined[0]["text"].endswith("Rs. 189.46 Cr claimed by KSEB Ltd.") and "SBU-G of KSEB" in joined[0]["text"]


def test_table_columns_are_recognised_from_the_previous_orders_headings():
    roles = order_draft._column_roles(["No", "Particulars", "MYT Order dated 25.06.2022", "Actuals", "TU Sought",
                                       "Difference over approval", "KSERC Approval"])
    assert roles == {2: "myt", 3: "actual", 4: "claim", 5: "difference", 6: "approved"}


def test_table_rows_fill_known_heads_and_leave_other_figures_as_placeholders():
    table = {"header": ["No", "Particulars", "MYT Order dated 25.06.2022", "Actuals", "TU Sought"],
             "data_rows": [["1", "Depreciation", "157.02", "159.67", "159.67"], ["2", "Unlisted head", "1.50", "1.50", "1.50"]]}
    fields = order_draft._fields_by_key({"fields": [{"field_label": "Depreciation", "arr_approved": "175.00",
                                                     "petition_claimed": "182.74", "petition_actuals": "772.04"}]})
    rows = order_draft._table_rows(table, fields)
    assert rows[0] == ["1", "Depreciation", "175.00", "772.04", "182.74"]
    assert rows[1] == ["2", "Unlisted head", "[[ ]]", "[[ ]]", "[[ ]]"]
