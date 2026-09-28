import json
import uuid
from pathlib import Path

UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


def new_doc_id():
    return uuid.uuid4().hex


def doc_dir(doc_id):
    d = UPLOADS_DIR / doc_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def pdf_path(doc_id):
    return doc_dir(doc_id) / "source.pdf"


def data_path(doc_id):
    return doc_dir(doc_id) / "data.json"


def save_data(doc_id, data):
    with open(data_path(doc_id), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_data(doc_id):
    path = data_path(doc_id)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_docs():
    docs = []
    for d in UPLOADS_DIR.iterdir():
        if d.is_dir() and (d / "data.json").exists():
            data = load_data(d.name)
            docs.append({
                "doc_id": d.name,
                "filename": data.get("filename"),
                "chapter_heading": data.get("chapter_heading"),
                "pages": data.get("pages"),
                "order_table_count": len(data.get("order_tables", [])),
                "needs_review_count": sum(1 for t in data.get("order_tables", []) if t.get("needs_review")),
            })
    return docs
