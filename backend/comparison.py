import json
import uuid
from pathlib import Path

import storage
from extraction.schema_discovery import discover_schema
from extraction.arr_budget import extract_arr_budget
from extraction.petition_claims import match_schema_to_petition
from extraction.compare import build_comparison, to_float

COMPARISONS_DIR = Path(__file__).parent / "comparisons"
COMPARISONS_DIR.mkdir(exist_ok=True)

# "Sensible starting values" per the project brief - not tuned against a
# large body of real deviations yet, just a reasonable first cut (SBU-G's
# cost components run from single-digit to hundreds of Cr, so a pure %
# threshold alone would flag tiny near-zero items on any swing at all;
# the absolute floor exists specifically to suppress that noise). Fully
# editable per comparison from the dashboard - see update_settings.
DEFAULT_SETTINGS = {"pct_threshold": 10.0, "abs_threshold": 1.0}


def new_comparison_id():
    return uuid.uuid4().hex


def comparison_dir(comparison_id):
    d = COMPARISONS_DIR / comparison_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def data_path(comparison_id):
    return comparison_dir(comparison_id) / "data.json"


def save_comparison(comparison_id, data):
    with open(data_path(comparison_id), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_comparison(comparison_id):
    path = data_path(comparison_id)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_comparisons():
    out = []
    for d in COMPARISONS_DIR.iterdir():
        if d.is_dir() and (d / "data.json").exists():
            data = load_comparison(d.name)
            flagged = sum(
                1 for f in data.get("fields", [])
                if f.get("needs_review") or _is_significant(f, data.get("settings", DEFAULT_SETTINGS))
            )
            out.append({
                "comparison_id": d.name,
                "target_year": data.get("target_year"),
                "tuo_filename": data.get("tuo_filename"),
                "arr_filename": data.get("arr_filename"),
                "petition_filename": data.get("petition_filename"),
                "field_count": len(data.get("fields", [])),
                "flagged_count": flagged,
            })
    return out


def _is_significant(field, settings):
    """A deviation is "significant" only when it clears BOTH the
    percentage threshold AND the absolute floor - see DEFAULT_SETTINGS'
    docstring for why a single knob isn't enough across fields this
    different in scale."""
    pct = field.get("deviation_pct")
    absval = field.get("deviation_abs")
    if pct is None or absval is None:
        return False
    return abs(pct) >= settings["pct_threshold"] and abs(absval) >= settings["abs_threshold"]


def build(tuo_doc_id, arr_doc_id, petition_doc_id, target_year):
    """Run stages (i)-(iii) against three already-uploaded documents'
    stored extraction data (not re-parsing any PDF from scratch - the
    upload flow already did that once) and produce a saved comparison."""
    tuo_data = storage.load_data(tuo_doc_id)
    arr_data = storage.load_data(arr_doc_id)
    petition_data = storage.load_data(petition_doc_id)
    if tuo_data is None or arr_data is None or petition_data is None:
        missing = [name for name, d in
                   (("truing-up order", tuo_data), ("ARR", arr_data), ("petition", petition_data))
                   if d is None]
        return {"error": f"Document(s) not found: {', '.join(missing)}"}

    schema_fields = discover_schema(tuo_data["order_tables"])
    arr_budget = extract_arr_budget(schema_fields, arr_data["order_tables"], target_year)
    petition_pdf_path = str(storage.pdf_path(petition_doc_id))
    petition_claims = match_schema_to_petition(schema_fields, petition_data["order_tables"], petition_pdf_path)
    fields = build_comparison(arr_budget, petition_claims)

    comparison_id = new_comparison_id()
    data = {
        "comparison_id": comparison_id,
        "tuo_doc_id": tuo_doc_id,
        "arr_doc_id": arr_doc_id,
        "petition_doc_id": petition_doc_id,
        "tuo_filename": tuo_data.get("filename"),
        "arr_filename": arr_data.get("filename"),
        "petition_filename": petition_data.get("filename"),
        "target_year": target_year,
        "schema_field_count": len(schema_fields),
        "settings": dict(DEFAULT_SETTINGS),
        "fields": fields,
    }
    save_comparison(comparison_id, data)
    return data
