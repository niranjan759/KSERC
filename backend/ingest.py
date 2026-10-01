"""Turning an uploaded PDF into stored per-SBU extractions. Runs off the
request thread: extracting all three SBU chapters from a large document
(the 493-page ARR) takes minutes, far longer than an upload request should
be held open."""
import threading

import storage
from extraction.extract_sbu_g import extract_all_sections

BUCKETS = ("order_tables", "reference_tables", "unclassified_fragments")

EXTRACTION_VERSION = storage.EXTRACTION_VERSION
NOT_REGULATORY = ("No SBU chapter was found - this doesn't look like a KSERC Truing Up Order, "
                  "ARR order or truing-up petition.")

_backfill_lock = threading.Lock()


def _mark_unreviewed(sections):
    for s in sections.values():
        for bucket in BUCKETS:
            for t in s.get(bucket, []):
                t["reviewed"] = False


def _fail(doc_id, filename, message):
    # a refused upload shouldn't leave its file behind on disk
    storage.pdf_path(doc_id).unlink(missing_ok=True)
    storage.set_status(doc_id, {"state": "failed", "filename": filename, "error": message})


def process_upload(doc_id, filename):
    try:
        sections = extract_all_sections(str(storage.pdf_path(doc_id)))
    except Exception:
        _fail(doc_id, filename, "Couldn't read this PDF.")
        return
    if all("error" in sections[k] for k in storage.SBUS):
        _fail(doc_id, filename, NOT_REGULATORY)
        return
    _mark_unreviewed(sections)
    data = {"doc_id": doc_id, "filename": filename, "sbus": sections,
            "extraction_version": EXTRACTION_VERSION}
    storage.get_meta(doc_id, data)
    storage.save_data(doc_id, data)
    storage.clear_status(doc_id)


def _carry_over_reviewed(old_sbus, new_sbus):
    """Keep a reviewer's work across a re-extraction: any table they marked
    reviewed keeps its (possibly hand-edited) rows and the flag, matched to
    the new extraction by table number and title. Unreviewed tables take the
    new extraction - that's the point of re-extracting."""
    kept = 0
    for sbu, old in (old_sbus or {}).items():
        new = new_sbus.get(sbu)
        if not new or "error" in new or "error" in old:
            continue
        for bucket in BUCKETS:
            reviewed = {(t.get("table_no"), t.get("title")): t for t in old.get(bucket, []) if t.get("reviewed")}
            for t in new.get(bucket, []):
                prev = reviewed.get((t.get("table_no"), t.get("title")))
                if prev:
                    t["data_rows"], t["reviewed"] = prev["data_rows"], True
                    kept += 1
    return kept


def backfill_sections():
    """Re-extract stored documents produced by older extraction code (see
    EXTRACTION_VERSION) - including documents from before SBU-T/D existed.
    Tables a reviewer marked reviewed are carried over, not overwritten."""
    with _backfill_lock:
        for d in storage.UPLOADS_DIR.iterdir():
            if not (d.is_dir() and (d / "data.json").exists()):
                continue
            data = storage.load_data(d.name)
            if data.get("extraction_version", 1) >= EXTRACTION_VERSION:
                continue
            try:
                sections = extract_all_sections(str(storage.pdf_path(d.name)))
            except Exception:
                continue
            _mark_unreviewed(sections)
            data = storage.load_data(d.name)  # re-read: an edit may have landed meanwhile
            _carry_over_reviewed(data.get("sbus"), sections)
            data["sbus"] = sections
            data["extraction_version"] = EXTRACTION_VERSION
            storage.save_data(d.name, data)


def start_backfill():
    threading.Thread(target=backfill_sections, daemon=True).start()
