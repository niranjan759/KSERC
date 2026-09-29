import shutil
from pathlib import Path

import fitz  # PyMuPDF
from fastapi import BackgroundTasks, FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from extraction.compare import to_float
from extraction.extract_sbu_g import SBU_NAMES
import comparison
import ingest
import storage

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = FastAPI(title="KSERC Truing-Up Review API")


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
    if bucket not in ("order_tables", "reference_tables", "unclassified_fragments"):
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
    if "arr_approved" in update:
        field["arr_approved"] = update["arr_approved"]
    if "petition_claimed" in update:
        field["petition_claimed"] = update["petition_claimed"]
    if "reviewed" in update:
        field["reviewed"] = bool(update["reviewed"])

    if "arr_approved" in update or "petition_claimed" in update:
        approved = to_float(field["arr_approved"])
        claimed = to_float(field["petition_claimed"])
        if approved is not None and claimed is not None:
            field["deviation_abs"] = round(claimed - approved, 2)
            field["deviation_pct"] = round(field["deviation_abs"] / abs(approved) * 100, 2) if approved != 0 else None
        else:
            field["deviation_abs"] = None
            field["deviation_pct"] = None

    comparison.save_comparison(comparison_id, data)
    return field


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
