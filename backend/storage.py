import json
import re
import uuid
from pathlib import Path

import doc_meta

UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

SBUS = ("G", "T", "D")

# Bump whenever extraction output changes, so stored documents extracted by
# older code are redone on the next server start rather than kept stale
# (see ingest.backfill_sections).
#   1 - SBU-G only (no version field)
#   2 - all three SBUs; cross-row text overflow fix; page-break
#       continuations merged even when the column count changes; nested
#       duplicate tables dropped
EXTRACTION_VERSION = 2
SECTION_KEYS = ("order_tables", "reference_tables", "unclassified_fragments", "chapter_heading", "pages")


def new_doc_id():
    return uuid.uuid4().hex


class InvalidId(ValueError):
    pass


def check_id(some_id):
    # IDs arrive straight from URL path segments and are joined onto
    # directories we mkdir/read/delete - on Windows an encoded backslash
    # ("..\uploads\x") would otherwise escape the intended folder.
    if not re.fullmatch(r'[0-9a-f]{32}', some_id or ""):
        raise InvalidId(f"Invalid id: {some_id!r}")


def doc_dir(doc_id):
    check_id(doc_id)
    return UPLOADS_DIR / doc_id


def pdf_path(doc_id):
    return doc_dir(doc_id) / "source.pdf"


def data_path(doc_id):
    return doc_dir(doc_id) / "data.json"


def status_path(doc_id):
    return doc_dir(doc_id) / "status.json"


def save_data(doc_id, data):
    doc_dir(doc_id).mkdir(parents=True, exist_ok=True)
    with open(data_path(doc_id), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_data(doc_id):
    path = data_path(doc_id)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "sbus" not in data:
        # uploaded before per-SBU extraction existed: only SBU-G was
        # extracted, stored at the top level. Presented in the current
        # shape; T and D are filled in by backfill_sections().
        data["sbus"] = {"G": {k: data.pop(k) for k in SECTION_KEYS if k in data}}
    return data


def section(data, sbu):
    """One SBU's extracted section, or None if the document has no chapter
    for it (or it hasn't been extracted yet)."""
    s = (data.get("sbus") or {}).get(sbu)
    if not s or "error" in s:
        return None
    return s


def primary_section(data):
    """A section to classify the document by - its SBU-G chapter when it has
    one, otherwise whichever SBU chapter it does have."""
    for sbu in SBUS:
        s = section(data, sbu)
        if s:
            return s
    return {}


def set_status(doc_id, status):
    doc_dir(doc_id).mkdir(parents=True, exist_ok=True)
    with open(status_path(doc_id), "w", encoding="utf-8") as f:
        json.dump(status, f)


def clear_status(doc_id):
    status_path(doc_id).unlink(missing_ok=True)


def get_meta(doc_id, data=None):
    """Document type / year, computed once and cached in data.json -
    documents uploaded before type detection existed are backfilled the
    first time they're asked for."""
    data = data if data is not None else load_data(doc_id)
    if data is None:
        return None
    if "doc_meta" not in data:
        data["doc_meta"] = doc_meta.classify(primary_section(data), pdf_path(doc_id))
        save_data(doc_id, data)
    return data["doc_meta"]


def list_docs():
    docs = []
    for d in UPLOADS_DIR.iterdir():
        if not d.is_dir():
            continue
        if (d / "data.json").exists():
            data = load_data(d.name)
            meta = get_meta(d.name, data)
            g = section(data, "G") or {}
            docs.append({
                "doc_id": d.name,
                "state": "ready",
                "updating": data.get("extraction_version", 1) < EXTRACTION_VERSION,
                "filename": data.get("filename"),
                "sbus_available": [s for s in SBUS if section(data, s)],
                "order_table_count": sum(len((section(data, s) or {}).get("order_tables", [])) for s in SBUS),
                "needs_review_count": sum(1 for s in SBUS for t in (section(data, s) or {}).get("order_tables", [])
                                          if t.get("needs_review")),
                "chapter_heading": g.get("chapter_heading"),
                "doc_type": meta["doc_type"],
                "fiscal_year": meta["fiscal_year"],
                "control_period": meta["control_period"],
                "label": doc_meta.describe(meta),
            })
        elif (d / "status.json").exists():
            with open(d / "status.json", "r", encoding="utf-8") as f:
                status = json.load(f)
            docs.append({"doc_id": d.name, **status})
    return docs
