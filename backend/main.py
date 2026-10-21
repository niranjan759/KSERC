import shutil
from pathlib import Path

import fitz  # PyMuPDF
from fastapi import BackgroundTasks, FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from extraction.extract_sbu_g import SBU_NAMES
import comparison
import order_draft
import ingest
import storage

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = FastAPI(title="KSERC Truing-Up Review API")


@app.middleware("http")
async def revalidate_frontend(request, call_next):
    """Make browsers check for a newer app.js / styles.css on every load.
    Without this a browser kept running an old app.js after an update
    (download buttons that no longer matched the server). Unchanged files
    still come back as a cheap 304 Not Modified."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(storage.InvalidId)
async def invalid_id_handler(request, exc):
    return JSONResponse(status_code=404, content={"detail": "Not found"})


@app.on_event("startup")
def backfill_older_uploads():
    ingest.start_backfill()


@app.post("/api/documents/upload")
async def upload_document(background: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported")

    doc_id = storage.new_doc_id()
    pdf_path = storage.pdf_path(doc_id)
    contents = await file.read()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(contents)
    storage.set_status(doc_id, {"state": "processing", "filename": file.filename})
    background.add_task(ingest.process_upload, doc_id, file.filename)
    return {"doc_id": doc_id, "filename": file.filename, "state": "processing"}


@app.get("/api/documents")
def list_documents():
    return storage.list_docs()


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    data = storage.load_data(doc_id)
    if data is None:
        raise HTTPException(404, "Document not found")
    return data


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    d = storage.doc_dir(doc_id)
    if not d.exists():
        raise HTTPException(404, "Document not found")
    shutil.rmtree(d)
    return {"deleted": doc_id}


@app.patch("/api/documents/{doc_id}/{bucket}/{index}")
async def update_table(doc_id: str, bucket: str, index: int, update: dict, sbu: str = "G"):
    if bucket not in ("order_tables", "reference_tables", "appendix_tables", "unclassified_fragments"):
        raise HTTPException(400, "Invalid bucket")
    data = storage.load_data(doc_id)
    if data is None:
        raise HTTPException(404, "Document not found")
    sec = storage.section(data, sbu)
    if sec is None:
        raise HTTPException(404, f"This document has no SBU-{sbu} section")
    tables = sec[bucket]
    if index < 0 or index >= len(tables):
        raise HTTPException(404, "Table not found")

    if "data_rows" in update:
        tables[index]["data_rows"] = update["data_rows"]
    if "reviewed" in update:
        tables[index]["reviewed"] = bool(update["reviewed"])

    storage.save_data(doc_id, data)
    return tables[index]


@app.get("/api/documents/{doc_id}/page/{page_number}.png")
def get_page_image(doc_id: str, page_number: int, scale: float = 2.0):
    path = storage.pdf_path(doc_id)
    if not path.exists():
        raise HTTPException(404, "Document not found")
    with fitz.open(path) as pdf:
        if page_number < 1 or page_number > len(pdf):
            raise HTTPException(404, "Page out of range")
        page = pdf[page_number - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        png_bytes = pix.tobytes("png")
    return Response(content=png_bytes, media_type="image/png")


@app.post("/api/comparisons")
async def create_comparison(body: dict):
    for key in ("tuo_doc_id", "arr_doc_id", "petition_doc_id", "target_year"):
        if not body.get(key):
            raise HTTPException(400, f"Missing required field: {key}")
    data = comparison.build(body["tuo_doc_id"], body["arr_doc_id"], body["petition_doc_id"],
                            body["target_year"], body.get("sbu", "G"))
    if "error" in data:
        raise HTTPException(422, data["error"])
    return data


@app.get("/api/sbus")
def list_sbus():
    return [{"sbu": s, "name": SBU_NAMES[s], "comparable": s in comparison.mapped_sbus()} for s in storage.SBUS]


@app.get("/api/comparisons")
def list_comparisons():
    return comparison.list_comparisons()


@app.get("/api/comparisons/{comparison_id}")
def get_comparison(comparison_id: str):
    data = comparison.load_comparison(comparison_id)
    if data is None:
        raise HTTPException(404, "Comparison not found")
    return comparison.ensure_checked(comparison_id, data)


@app.delete("/api/comparisons/{comparison_id}")
def delete_comparison(comparison_id: str):
    if not comparison.delete_comparison(comparison_id):
        raise HTTPException(404, "Comparison not found")
    return {"deleted": comparison_id}


@app.patch("/api/comparisons/{comparison_id}/fields/{index}")
async def update_comparison_field(comparison_id: str, index: int, update: dict):
    data = comparison.load_comparison(comparison_id)
    if data is None:
        raise HTTPException(404, "Comparison not found")
    fields = data["fields"]
    if index < 0 or index >= len(fields):
        raise HTTPException(404, "Field not found")

    field = fields[index]
    if "excluded" in update:
        # taken out of the draft order (or put back) - the comparison keeps it
        field["excluded"] = bool(update["excluded"])
    if "arr_approved" in update:
        field["arr_approved"] = update["arr_approved"]
        has_value = str(update["arr_approved"] or "").strip() != ""
        # a figure typed in for a line the ARR doesn't carry (or that is new
        # this year) replaces the "no ARR line" note; clearing it restores it
        if has_value and field.get("note"):
            field["note_original"], field["note"], field["arr_manual"] = field["note"], None, True
        elif has_value and field.get("new_in_petition") and not field.get("arr_pages"):
            field["arr_manual"] = True
            field["needs_review"] = False
            field["lookup_problem"] = None
        elif not has_value and field.get("arr_manual"):
            field["arr_manual"] = False
            field["note"] = field.pop("note_original", None)
    if "petition_claimed" in update:
        field["petition_claimed"] = update["petition_claimed"]
        has_claim = str(update["petition_claimed"] or "").strip() != ""
        # same idea as arr_approved above: a figure the reviewer found near
        # the missing one replaces the "no separate claim" note
        if has_claim and field.get("claim_note"):
            field["claim_note_original"], field["claim_note"], field["claim_manual"] = field["claim_note"], None, True
        elif not has_claim and field.get("claim_manual"):
            field["claim_manual"] = False
            field["claim_note"] = field.pop("claim_note_original", None)
    if "reviewed" in update:
        field["reviewed"] = bool(update["reviewed"])

    if "arr_approved" in update or "petition_claimed" in update:
        comparison.compute_deviation(field)

    if any(k in update for k in ("decision", "commission_approved", "reason")):
        try:
            order_draft.apply_decision(field, update)
        except ValueError as e:
            raise HTTPException(400, str(e))

    comparison.save_comparison(comparison_id, data)
    return field


@app.post("/api/comparisons/{comparison_id}/accept-remaining")
def accept_remaining_claims(comparison_id: str):
    """The reviewer's "Accept all remaining claims": every item still pending
    that has a claim is recorded as accepted. Nothing is accepted otherwise -
    items start pending (order_draft.decision_of)."""
    data = comparison.load_comparison(comparison_id)
    if data is None:
        raise HTTPException(404, "Comparison not found")
    accepted = order_draft.accept_remaining_claims(data["fields"])
    comparison.save_comparison(comparison_id, data)
    return {"accepted": accepted, "fields": data["fields"]}


@app.get("/api/comparisons/{comparison_id}/fields/{index}/precedent")
def field_precedent(comparison_id: str, index: int):
    data = comparison.load_comparison(comparison_id)
    if data is None:
        raise HTTPException(404, "Comparison not found")
    if index < 0 or index >= len(data["fields"]):
        raise HTTPException(404, "Field not found")
    return order_draft.precedent(data, index)


@app.get("/api/comparisons/{comparison_id}/order.docx")
def download_order_draft(comparison_id: str, scope: str = "full"):
    """scope=full: the whole order laid out like the previous one;
    scope=chapter: just this comparison's SBU chapter, as a short summary."""
    name, content = _order_draft(comparison_id, scope)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{name}.docx"'})


@app.get("/api/comparisons/{comparison_id}/order.pdf")
def download_order_pdf(comparison_id: str, scope: str = "full"):
    """The same draft as order.docx, converted to PDF by LibreOffice."""
    import order_pdf
    name, content = _order_draft(comparison_id, scope)
    try:
        content = order_pdf.docx_to_pdf(content)
    except order_pdf.NoConverter as e:
        raise HTTPException(503, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return Response(content=content, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})


def _order_draft(comparison_id, scope):
    """(file name without extension, .docx bytes) of a comparison's draft."""
    data = comparison.load_comparison(comparison_id)
    if data is None:
        raise HTTPException(404, "Comparison not found")
    if data.get("input_errors"):
        raise HTTPException(422, "This comparison's inputs were refused; no order can be drafted from it.")
    suffix = "DRAFT" if scope == "full" else "CHAPTER_DRAFT"
    name = f"Truing_Up_Order_{data['target_year']}_{suffix}" if scope == "full" else \
        f"Truing_Up_Order_SBU-{data.get('sbu', 'G')}_{data['target_year']}_{suffix}"
    try:
        if scope == "full":
            data = comparison.ensure_refs(comparison_id, data)  # fills in the petition's actuals on older comparisons
            content = order_draft.build_full_docx(data)
        else:
            content = order_draft.build_docx(data)
    except ModuleNotFoundError as e:
        raise HTTPException(503, f"The Word export needs the '{e.name}' package. "
                                 f"Install it with: pip install -r backend/requirements.txt")
    except LookupError as e:
        raise HTTPException(409, str(e))
    return name, content


@app.get("/api/comparisons/{comparison_id}/fields/{index}/nearby")
def field_nearby(comparison_id: str, index: int, side: str = "arr"):
    if side not in ("arr", "petition"):
        raise HTTPException(400, "side must be arr or petition")
    data = comparison.load_comparison(comparison_id)
    if data is None:
        raise HTTPException(404, "Comparison not found")
    if index < 0 or index >= len(data["fields"]):
        raise HTTPException(404, "Field not found")
    data = comparison.ensure_refs(comparison_id, data)
    return comparison.nearby(data, index, side)


@app.get("/api/comparisons/{comparison_id}/candidates")
def comparison_candidates(comparison_id: str, q: str = ""):
    data = comparison.load_comparison(comparison_id)
    if data is None:
        raise HTTPException(404, "Comparison not found")
    return comparison.petition_candidates(data, q)


@app.post("/api/comparisons/{comparison_id}/fields")
async def add_comparison_field(comparison_id: str, body: dict):
    data = comparison.load_comparison(comparison_id)
    if data is None:
        raise HTTPException(404, "Comparison not found")
    field = comparison.add_field(data, body)
    if "error" in field:
        raise HTTPException(422, field["error"])
    comparison.save_comparison(comparison_id, data)
    return field


@app.delete("/api/comparisons/{comparison_id}/fields/{index}")
def remove_comparison_field(comparison_id: str, index: int):
    """Dismiss a line the reviewer decides doesn't belong. Only lines that
    were new in the petition can be removed; the mapped ones are the
    comparison's own fields."""
    data = comparison.load_comparison(comparison_id)
    if data is None:
        raise HTTPException(404, "Comparison not found")
    if index < 0 or index >= len(data["fields"]):
        raise HTTPException(404, "Field not found")
    if not data["fields"][index].get("new_in_petition"):
        raise HTTPException(400, "Only new petition lines can be removed")
    removed = data["fields"].pop(index)
    comparison.save_comparison(comparison_id, data)
    return {"removed": removed["field_label"]}


@app.patch("/api/comparisons/{comparison_id}/settings")
async def update_comparison_settings(comparison_id: str, update: dict):
    data = comparison.load_comparison(comparison_id)
    if data is None:
        raise HTTPException(404, "Comparison not found")
    if "pct_threshold" in update:
        data["settings"]["pct_threshold"] = float(update["pct_threshold"])
    if "abs_threshold" in update:
        data["settings"]["abs_threshold"] = float(update["abs_threshold"])
    comparison.save_comparison(comparison_id, data)
    return data["settings"]


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
