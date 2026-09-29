import json
import shutil
import uuid
from pathlib import Path

import doc_meta
import storage
from extraction.schema_discovery import discover_schema
from extraction.arr_budget import ARR_FIELD_MAPS, extract_arr_budget
from extraction.petition_claims import PETITION_TABLES_BY_SBU, match_schema_to_petition, new_petition_lines
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
    storage.check_id(comparison_id)
    return COMPARISONS_DIR / comparison_id


def data_path(comparison_id):
    return comparison_dir(comparison_id) / "data.json"


def save_comparison(comparison_id, data):
    comparison_dir(comparison_id).mkdir(parents=True, exist_ok=True)
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
            data = ensure_checked(d.name, load_comparison(d.name))
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
                "sbu": data.get("sbu", "G"),
                "field_count": len(data.get("fields", [])),
                "flagged_count": flagged,
                "has_errors": bool(data["input_errors"]),
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


SLOTS = (
    ("tuo", "truing_up_order", "Truing Up Order (schema source)"),
    ("arr", "arr", "ARR"),
    ("petition", "petition", "Petition"),
)


def check_inputs(ids, metas, target_year_raw):
    """Refuse a comparison whose inputs can't produce meaningful numbers,
    instead of silently computing garbage - confirmed necessary from real
    use: comparisons had been created with a petition in the ARR slot, a
    petition in the Truing Up Order slot, and a year typed as "23-24", all
    accepted without complaint. Returns (normalized_year, errors, warnings);
    errors block creation, warnings are shown but don't."""
    errors, warnings = [], []
    year = doc_meta.normalize_year(target_year_raw)
    if not year:
        errors.append(f'"{target_year_raw}" isn\'t a financial year - enter it as YYYY-YY, e.g. 2024-25.')

    if len(set(ids.values())) < len(ids):
        errors.append("The same document is selected in more than one slot.")

    for slot, expected, slot_label in SLOTS:
        meta = metas[slot]
        if meta["doc_type"] == "unknown":
            warnings.append(f"Couldn't confirm the {slot_label} document's type from its contents - check it's the right file.")
        elif meta["doc_type"] != expected:
            errors.append(f"The {slot_label} slot has {doc_meta.with_article(doc_meta.describe(meta))}, "
                          f"not {doc_meta.with_article(doc_meta.DOC_TYPE_LABELS[expected])}.")

    if year and not errors:
        period = metas["arr"].get("control_period") or []
        if period and year not in period:
            errors.append(f"The ARR covers {period[0]} to {period[-1]}; FY {year} is outside it. "
                          f"Upload the ARR order for the control period that includes {year}.")
        pet_year = metas["petition"].get("fiscal_year")
        if pet_year and pet_year != year:
            errors.append(f"The petition is for FY {pet_year}, but the target year is {year}.")
        tuo_year = metas["tuo"].get("fiscal_year")
        if tuo_year and tuo_year >= year:
            warnings.append(f"The Truing Up Order is for FY {tuo_year} - normally the previous year's order "
                            f"is used as the template for FY {year}.")
    return year, errors, warnings


def _metas(ids):
    return {slot: storage.get_meta(doc_id) for slot, doc_id in ids.items()}


def coverage_warnings(fields):
    """A document from a new year can lay its tables out differently from
    the 2023-24 / 2024-25 ones this pipeline was verified against. When
    that happens the symptom is missing values, not an error - so say so
    rather than show a dashboard full of blanks with no explanation."""
    warnings = []
    if fields and not any(f.get("petition_claimed") not in (None, "") for f in fields):
        warnings.append("No claimed values were found in the petition. Its summary tables may be laid out "
                        "differently from the petitions this was verified against - check the source pages.")
    if fields and not any(f.get("arr_approved") not in (None, "") for f in fields):
        warnings.append("No approved values were found in the ARR for this year. Its tables may be laid out "
                        "differently from the ARR this was verified against - check the source pages.")
    if not fields:
        warnings.append("No fields could be compared at all - the documents' tables weren't recognised.")
    return warnings


def ensure_checked(comparison_id, data):
    """Comparisons created before input checking existed get checked the
    first time they're opened, so a mismatched one is labelled as such
    rather than presented as if its numbers meant something."""
    ids = {"tuo": data["tuo_doc_id"], "arr": data["arr_doc_id"], "petition": data["petition_doc_id"]}
    deleted_msg = "One or more of this comparison's documents has been deleted."
    if any(not storage.data_path(i).exists() for i in ids.values()):
        if deleted_msg not in data.get("input_errors", []):
            data["input_errors"] = data.get("input_errors", []) + [deleted_msg]
            data.setdefault("input_warnings", [])
            save_comparison(comparison_id, data)
        return data
    if "input_errors" in data:
        return data
    try:
        metas = _metas(ids)
    except FileNotFoundError:
        metas = None
    if metas is None or any(m is None for m in metas.values()):
        data["input_errors"] = ["One or more of this comparison's documents has been deleted."]
        data["input_warnings"] = []
    else:
        _, errors, warnings = check_inputs(ids, metas, data.get("target_year"))
        data["input_errors"] = errors
        data["input_warnings"] = warnings + coverage_warnings(data.get("fields", []))
    save_comparison(comparison_id, data)
    return data


def delete_comparison(comparison_id):
    storage.check_id(comparison_id)
    d = COMPARISONS_DIR / comparison_id
    if not (d / "data.json").exists():
        return False
    shutil.rmtree(d)
    return True


def mapped_sbus():
    return sorted(set(ARR_FIELD_MAPS) & set(PETITION_TABLES_BY_SBU), key="GTD".index)


def build(tuo_doc_id, arr_doc_id, petition_doc_id, target_year, sbu="G"):
    """Run stages (i)-(iii) for one SBU against three already-uploaded
    documents' stored extraction data (not re-parsing any PDF from scratch -
    the upload flow already did that once) and produce a saved comparison."""
    if sbu not in mapped_sbus():
        return {"error": f"SBU-{sbu} comparisons aren't available yet - its field mapping "
                         f"hasn't been built and verified."}
    tuo_data = storage.load_data(tuo_doc_id)
    arr_data = storage.load_data(arr_doc_id)
    petition_data = storage.load_data(petition_doc_id)
    if tuo_data is None or arr_data is None or petition_data is None:
        missing = [name for name, d in
                   (("truing-up order", tuo_data), ("ARR", arr_data), ("petition", petition_data))
                   if d is None]
        return {"error": f"Document(s) not found: {', '.join(missing)}"}

    ids = {"tuo": tuo_doc_id, "arr": arr_doc_id, "petition": petition_doc_id}
    metas = {"tuo": storage.get_meta(tuo_doc_id, tuo_data),
             "arr": storage.get_meta(arr_doc_id, arr_data),
             "petition": storage.get_meta(petition_doc_id, petition_data)}
    target_year, errors, warnings = check_inputs(ids, metas, target_year)
    if errors:
        return {"error": " ".join(errors)}

    secs = {"tuo": storage.section(tuo_data, sbu), "arr": storage.section(arr_data, sbu),
            "petition": storage.section(petition_data, sbu)}
    missing = [label for slot, _, label in SLOTS if secs[slot] is None]
    if missing:
        return {"error": f"No SBU-{sbu} section in: {', '.join(missing)}. If this document was uploaded "
                         f"recently it may still be processing - try again in a few minutes."}

    schema_fields = discover_schema(secs["tuo"]["order_tables"])
    schema_fields += new_petition_lines(schema_fields, secs["petition"]["order_tables"], sbu)
    arr_budget = extract_arr_budget(schema_fields, secs["arr"]["order_tables"], target_year, sbu)
    petition_pdf_path = str(storage.pdf_path(petition_doc_id))
    petition_claims = match_schema_to_petition(schema_fields, secs["petition"]["order_tables"], petition_pdf_path, sbu)
    fields = build_comparison(arr_budget, petition_claims)

    comparison_id = new_comparison_id()
    data = {
        "comparison_id": comparison_id,
        "sbu": sbu,
        "tuo_doc_id": tuo_doc_id,
        "arr_doc_id": arr_doc_id,
        "petition_doc_id": petition_doc_id,
        "tuo_filename": tuo_data.get("filename"),
        "arr_filename": arr_data.get("filename"),
        "petition_filename": petition_data.get("filename"),
        "target_year": target_year,
        "tuo_label": doc_meta.describe(metas["tuo"]),
        "arr_label": doc_meta.describe(metas["arr"]),
        "petition_label": doc_meta.describe(metas["petition"]),
        "schema_field_count": len(schema_fields),
        "settings": dict(DEFAULT_SETTINGS),
        "input_errors": [],
        "input_warnings": warnings + coverage_warnings(fields),
        "fields": fields,
    }
    save_comparison(comparison_id, data)
    return data
