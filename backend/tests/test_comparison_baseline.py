"""Every comparison figure hand-verified against the source PDFs (SBU-G/T/D,
FY2023-24 and FY2024-25, schema from the 2023-24 Truing Up Order) must keep
coming out the same. A failure means an extraction or mapping change moved
a figure: check it against the PDF before updating the fixture.

Runs on the documents uploaded to this machine (backend/uploads isn't in
git): upload the 2023-24 Truing Up Order, the 2022-27 ARR and both
petitions, and wait for them to finish processing. Skipped otherwise."""
import json
import unicodedata
from pathlib import Path

import pytest

import storage
from extraction.arr_budget import extract_arr_budget
from extraction.compare import build_comparison
from extraction.petition_claims import match_schema_to_petition, new_petition_lines
from extraction.schema_discovery import discover_schema

BASELINE = json.loads((Path(__file__).parent / "fixtures" / "comparison_baseline.json").read_text(encoding="utf-8"))


def _find_doc(doc_type, year=None):
    for d in storage.list_docs():
        if d.get("state") == "ready" and not d.get("updating") and d.get("doc_type") == doc_type \
                and (year is None or d.get("fiscal_year") == year):
            return d["doc_id"]
    return None


def _key(label):
    # extracted labels carry odd dashes ("Pugalur – Thrissur"); compare letters/digits
    return "".join(ch for ch in unicodedata.normalize("NFKC", label or "") if ch.isalnum()).lower()


@pytest.mark.parametrize("case", sorted(BASELINE))
def test_comparison_matches_verified_baseline(case):
    sbu, year = case.split()
    ids = {"tuo": _find_doc("truing_up_order", "2023-24"), "arr": _find_doc("arr"),
           "petition": _find_doc("petition", year)}
    if not all(ids.values()):
        pytest.skip(f"needs uploaded documents: {[k for k, v in ids.items() if not v]}")
    secs = {slot: storage.section(storage.load_data(doc_id), sbu) for slot, doc_id in ids.items()}
    # the same steps comparison.build() runs
    schema = discover_schema(secs["tuo"]["order_tables"])
    schema += new_petition_lines(schema, secs["petition"]["order_tables"], sbu)
    fields = build_comparison(
        extract_arr_budget(schema, secs["arr"]["order_tables"], year, sbu),
        match_schema_to_petition(schema, secs["petition"]["order_tables"], str(storage.pdf_path(ids["petition"])), sbu))

    got = {_key(f["field_label"]): (f["arr_approved"] or None, f["petition_claimed"] or None) for f in fields}
    want = {_key(b["field"]): (b["approved"], b["claimed"]) for b in BASELINE[case]}
    assert got == want
