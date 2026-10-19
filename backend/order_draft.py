"""Stage (iv): draft the Truing Up Order chapter for one SBU from a reviewed
comparison.

Nothing here writes the Commission's reasoning. The wording is the previous
order's own sentence pattern filled with figures, and every decision and every
reason comes from the reviewer; whatever hasn't been decided yet is left as a
highlighted placeholder in the document, never filled with a guess."""
import io
import re

import storage
from extraction.compare import to_float
from extraction.arr_budget import label_key

DECISIONS = ("pending", "accepted", "modified", "disallowed")


def decision_of(field):
    """A field's decision. Until the reviewer chooses otherwise a field with a
    claim defaults to accepting it; one with no claim has nothing to accept
    and stays pending."""
    if field.get("decision"):
        return field["decision"]
    return "accepted" if field.get("petition_claimed") not in (None, "") else "pending"


def effective_approved(field):
    """The figure the Commission approves, as a string, or None while the
    field is undecided. Accepted / disallowed are derived from the claim, so
    editing the claim afterwards can't leave a stale approved figure behind."""
    decision = decision_of(field)
    if decision == "accepted":
        return field.get("petition_claimed") or None
    if decision == "disallowed":
        return "0.00"
    if decision == "modified":
        return field.get("commission_approved") or None
    return None


def apply_decision(field, update):
    """Record a reviewer's decision on one field. Typing an approved figure
    sets the decision for them: equal to the claim means accepted, anything
    else means modified."""
    if "decision" in update:
        decision = update["decision"] or "pending"
        if decision not in DECISIONS:
            raise ValueError(f"Unknown decision: {decision}")
        field["decision"] = decision
        if decision != "modified":
            field.pop("commission_approved", None)
    if "commission_approved" in update:
        value = str(update["commission_approved"] or "").strip()
        if value:
            claimed = to_float(field.get("petition_claimed"))
            typed = to_float(value)
            if typed is not None and claimed is not None and typed == claimed:
                field["decision"] = "accepted"
                field.pop("commission_approved", None)
            else:
                field["decision"] = "modified"
                field["commission_approved"] = value
        elif field.get("decision") == "modified":
            field["decision"] = "pending"
            field.pop("commission_approved", None)
    if "reason" in update:
        field["reason"] = str(update["reason"] or "").strip()
    return field


def included(fields):
    """The cost heads that go into the order: every compared field except
    the ones the reviewer removed on the draft-order page (`excluded`)."""
    return [f for f in fields if not f.get("excluded")]


def progress(fields):
    kept = included(fields)
    decided = sum(1 for f in kept if decision_of(f) != "pending")
    return {"decided": decided, "total": len(kept), "removed": len(fields) - len(kept)}


# --- last year's wording on the same head --------------------------------

STOPWORDS = {"for", "the", "and", "of", "to", "in", "on", "less", "net", "total"}
CLAUSE_SPLIT = re.compile(r'\n(?=\d{1,2}\.\d{1,3}(?:\.\d+)?\s)')


def precedent(data, index, limit=2):
    """Paragraphs of the previous Truing Up Order that discuss this field,
    for the reviewer to read while deciding - shown beside the decision,
    never copied into the draft."""
    field = data["fields"][index]
    label = (field.get("field_label") or "").strip()
    words = [w for w in label_key(label).split() if len(w) >= 3 and w not in STOPWORDS]
    if not words or (len(words) == 1 and len(words[0]) < 5):
        return []
    tuo = storage.load_data(data["tuo_doc_id"])
    sec = storage.section(tuo, data.get("sbu", "G")) if tuo else None
    if sec is None:
        return []
    hits = []
    for page in sec.get("text", []):
        for clause in CLAUSE_SPLIT.split(page["text"]):
            flat = re.sub(r'[^a-z0-9 ]', ' ', clause.lower().replace("&", " and "))
            flat = " " + re.sub(r'\s+', ' ', flat) + " "
            # most key words of the label must appear in the paragraph
            # ("O&M Expenses for existing stations" -> expenses, existing,
            # stations); the order often rewords one of them
            share = sum(f" {w} " in flat for w in words) / len(words)
            if share >= 0.6 and "commission" in flat:
                score = share + 0.1 * (("approv" in flat) + ("disallow" in flat or "not allow" in flat))
                hits.append((score, {"page": page["page"], "text": clause.strip()[:900]}))
    hits.sort(key=lambda h: -h[0])
    return [h[1] for h in hits[:limit]]


# --- the Word document ----------------------------------------------------

def _amount(value, unit):
    if value in (None, ""):
        return None
    unit = (unit or "").strip()
    return f"Rs. {value} Cr" if "cr" in unit.lower() else (f"{value} {unit}".strip())


def _template_facts(data):
    """Chapter number and the MYT order's date, read from the previous order
    so the draft keeps its numbering and cites the right order."""
    tuo = storage.load_data(data["tuo_doc_id"])
    sec = storage.section(tuo, data.get("sbu", "G")) if tuo else None
    chapter, myt_date = None, None
    if sec:
        m = re.search(r'CHAPTER\s*\S*\s*(\d+)', sec.get("chapter_heading") or "", re.I)
        chapter = m.group(1) if m else None
        for page in sec.get("text", []):
            m = re.search(r'ARR\s*&\s*ERC\s+Order\s+dated\s+(\d{2}\.\d{2}\.\d{4})', page["text"], re.I)
            if m:
                myt_date = m.group(1)
                break
    return chapter, myt_date


def _field_paragraphs(field, sbu_label, year):
    """The paragraphs for one field. The decision sentence follows the
    previous order's own wording; the reasoning is the reviewer's text or a
    placeholder."""
    label = field["field_label"]
    unit = field.get("unit")
    decision = decision_of(field)
    approved = effective_approved(field)
    claimed = field.get("petition_claimed")
    arr = field.get("arr_approved")
    reason = (field.get("reason") or "").strip()
    out = []

    if arr not in (None, ""):
        out.append(f"The MYT Order approved {_amount(arr, unit)} for {label} of {sbu_label} for the year {year}.")
    if claimed in (None, ""):
        claim_note = field.get("claim_note") or "KSEB Ltd has not claimed this item separately."
        out.append(claim_note if claim_note.endswith(".") else claim_note + ".")
    if decision == "pending" or (approved is None and claimed not in (None, "")):
        out.append(f"[[Commission's decision on {label} is pending - KSEB Ltd claimed "
                   f"{_amount(claimed, unit) or 'an amount not stated'}.]]")
        return out

    if decision == "disallowed":
        out.append(f"The Commission does not approve the claim of {_amount(claimed, unit)} towards {label} "
                   f"of {sbu_label} of KSEB Ltd for the year {year}.")
    elif approved is not None:
        against = f" as against {_amount(claimed, unit)} claimed by KSEB Ltd" if claimed not in (None, "") else ""
        out.append(f"As above, the Commission hereby approves {label} of {sbu_label} of KSEB Ltd for the "
                   f"year {year} at {_amount(approved, unit)}{against}.")
    if reason:
        out.append(reason)
    elif decision in ("modified", "disallowed"):
        out.append(f"[[Commission's reasoning for the change in {label} to be inserted.]]")
    return out


def build_docx(data):
    """The draft chapter as .docx bytes, typeset in the orders' house style
    (order_style): Arial, centred chapter title, Bold 13 headings, numbered
    clauses with hanging text, the Commission's conclusion in bold italic."""
    import order_style as house

    sbu = data.get("sbu", "G")
    year = data["target_year"]
    sbu_label = f"SBU-{sbu}"
    sbu_name = {"G": "Generation", "T": "Transmission", "D": "Distribution"}.get(sbu, sbu)
    fields = included(data["fields"])
    chapter, myt_date = _template_facts(data)
    ch = chapter or "[[n]]"

    doc = house.new_document()

    n = progress(data["fields"])
    removed = f" ({n['removed']} removed by the reviewer)" if n["removed"] else ""
    house.write_runs(doc.add_paragraph(),
                     f"DRAFT - prepared by the KSERC truing-up review tool for the Commission's consideration. "
                     f"{n['decided']} of {n['total']} items{removed} have a recorded decision; highlighted text marks "
                     f"what still needs the Commission's input. Figures are as printed in the petition and the "
                     f"ARR order and can be traced to their source pages in the review tool.", size=9, bold=True)

    house.chapter_heading(doc, f"CHAPTER-{ch}")
    house.chapter_heading(doc, "TRUING UP OF ACCOUNTS OF STRATEGIC BUSINESS UNIT")
    house.chapter_heading(doc, f"{sbu_name.upper()} ({sbu_label})")

    clause = 0
    conclusion = {"bold": True, "italic": True, "x0": house.LEFT_MARGIN_PT + house.HANG_PT}

    def numbered(text):
        nonlocal clause
        clause += 1
        return house.paragraph(doc, f"{ch}.{clause} {text}")

    numbered(f"KSEB Ltd has filed the petition for truing up of accounts of {sbu_label} for the year {year} "
             f"[[date of filing and petition number to be inserted]].")
    numbered(f"The summary of the ARR of {sbu_label} claimed by KSEB Ltd for the year {year}, with the figures "
             f"approved by the Commission, is given below.")

    header = ["Sl No", "Particulars", "MYT Order", "Claimed by KSEB Ltd", "Approved by Commission",
              "Approved less claimed"]
    rows = []
    for i, f in enumerate(fields, 1):
        approved = effective_approved(f)
        a, c = to_float(approved), to_float(f.get("petition_claimed"))
        diff = f"{round(a - c, 2):.2f}" if a is not None and c is not None else ""
        rows.append([str(i), f["field_label"], f.get("arr_approved") or "", f.get("petition_claimed") or "",
                     approved if approved is not None else "pending", diff])
    house.caption(doc, f"{ch}.1", f"Summary of the ARR of {sbu_label} for the year {year} - claimed and approved (Rs. Cr)")
    house.table(doc, header, rows, {"widths": [28, 170, 62, 65, 65, 65]}, ["", "", "(Rs. Cr)", "(Rs. Cr)", "(Rs. Cr)", "(Rs. Cr)"])

    numbered(f"The Commission has examined the ARR of {sbu_label} claimed by KSEB Ltd vis-a-vis the audited "
             f"accounts, the ARR&ERC Order dated {myt_date or '[[date of the MYT Order]]'}, the KSERC (Terms and "
             f"Conditions of Determination of Tariff) Regulations, 2021, and other relevant details, and decided as follows.")

    for f in fields:
        house.heading(doc, f["field_label"])
        # the order numbers a head's opening paragraph and runs the
        # conclusion on unnumbered beneath it, in bold italic as it does
        for k, text in enumerate(_field_paragraphs(f, sbu_label, year)):
            if k == 0:
                numbered(text)
            elif "Commission hereby approves" in text or "Commission does not approve" in text:
                house.paragraph(doc, text, conclusion)
            else:
                house.paragraph(doc, text)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# --- the whole order, laid out like the previous one ------------------------
#
# The previous Truing Up Order is the template: every chapter, in order, with
# its headings, numbered paragraphs and tables ("blocks", see
# extract_sbu_g.assemble_blocks). The new order follows that layout exactly.
# Wording is carried over with the financial year moved on; every figure and
# date in carried text is highlighted for checking, a table cell that no
# comparison supplies is left as a highlighted [ ], and a decision sentence is
# rewritten from the reviewer's decision. Nothing is invented.

FY_PAT = re.compile(r'\b(20\d\d)(\s*[-–]\s*)(\d{2})\b')
YEAR_END_DATE = re.compile(r'\b(31\.03|01\.04)\.(20\d\d)\b')
FIGURE_PAT = re.compile(r'\b\d{2}\.\d{2}\.\d{4}\b|\d[\d,]*\.\d+|\b\d{1,3}(?:,\d{3})+\b|\b\d{5,}\b')
CELL_FIGURE = re.compile(r'^\(?[-+]?\d*\.\d+\)?%?$|^\(?[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?$|^\d{4,}$')
DECISION_SENTENCE = re.compile(r'Commission hereby approves(?: the)? (?P<label>.+?) (?:of|for) (?:SBU-?\s?\w+ )?(?:of )?KSEB Ltd', re.I | re.S)
CLAUSE_START_PAT = re.compile(r'^\d{1,2}\.\d{1,3}(?:\.\d+)?\s')
HIGHLIGHT = re.compile(r'(\[\[.*?\]\]|\{\{.*?\}\})')


def shift_year(text):
    """The previous order's financial years moved on by one (2023-24 ->
    2024-25) and its year-end dates (31.03.2024 -> 31.03.2025)."""
    text = FY_PAT.sub(lambda m: f"{int(m.group(1)) + 1}{m.group(2)}{(int(m.group(3)) + 1) % 100:02d}", text)
    return YEAR_END_DATE.sub(lambda m: f"{m.group(1)}.{int(m.group(2)) + 1}", text)


def _mark_figures(text):
    """Highlight the figures and dates in carried-over wording; the clause
    number at the start is left alone."""
    lead = ""
    m = CLAUSE_START_PAT.match(text)
    if m:
        lead, text = text[:m.end()], text[m.end():]
    return lead + FIGURE_PAT.sub(lambda f: "{{" + f.group(0) + "}}", text)


def _column_roles(header):
    """Which of a table's columns carry the MYT figure, KSEB's claim and the
    Commission's approval, from the column headings."""
    roles = {}
    for i, h in enumerate(header):
        h = h or ""
        if re.search(r'actual|audited|accounts', h, re.I):
            roles[i] = "actual"
            continue
        # a heading of just "KSERC" is the Commission's column too (the
        # SBU-D summary reprinted in Chapter 7, Table 7.12)
        if re.search(r'KSERC\s*Approval|Approved by|^\s*KSERC\s*$', h, re.I):
            roles[i] = "approved"
        elif re.search(r'MYT|ARR\s*&?\s*ERC\s*Order|ARR\s*Approval', h, re.I):
            roles[i] = "myt"
        elif re.search(r'Sought|Truing\s*Up\s*(petition|claim)|TU\b', h, re.I):
            roles[i] = "claim"
        elif re.search(r'Difference over approval|Deviation from approval', h, re.I):
            roles[i] = "difference"
    return roles


def _fields_by_key(comparison):
    from extraction.arr_budget import label_key
    return {label_key(f["field_label"]): f for f in (comparison or {}).get("fields", [])}


def _lookup_field(fields_by_key, label):
    from extraction.arr_budget import label_key
    key = label_key(label)
    if key in fields_by_key:
        return fields_by_key[key]
    near = [f for k, f in fields_by_key.items() if k.startswith(key) or key.startswith(k)]
    if len(near) == 1:
        return near[0]
    totals = [f for f in near if "total" in f["field_label"].lower()]
    return totals[0] if len(totals) == 1 else None


def _table_rows(table, fields):
    """The table's data rows for the new order: a row whose label is a
    comparison field gets that field's figures in the MYT / claim / approved
    columns; every other figure is left as a highlighted [ ]."""
    from extraction.schema_discovery import find_label
    header = table.get("header") or []
    roles = _column_roles(header) if len(header) <= 8 else {}
    out = []
    from order_consolidated import is_number
    for row in table.get("data_rows", []):
        label, label_idx, _ = find_label(row)
        field = _lookup_field(fields, label) if (label and roles) else None
        if field and field.get("excluded"):
            continue  # a cost head the reviewer removed from the order
        # right of the row's label every number is a figure: one not filled
        # from the comparison is left blank, never carried over from last
        # year - a short one ("831", "42") included
        label_at = label_idx if label_idx is not None else 0
        cells = []
        for ci, cell in enumerate(row):
            text = (cell or "").strip()
            role = roles.get(ci)
            if field and role:
                if role == "myt":
                    value = field.get("arr_approved")
                elif role == "claim":
                    value = field.get("petition_claimed")
                elif role == "approved":
                    value = effective_approved(field)
                elif role == "actual":
                    value = field.get("petition_actuals")
                else:
                    a, c = to_float(field.get("arr_approved")), to_float(field.get("petition_claimed"))
                    value = f"{c - a:.2f}" if a is not None and c is not None else None
                cells.append(str(value) if value not in (None, "") else "[[ ]]")
            elif CELL_FIGURE.match(text) or (ci > label_at and is_number(text)):
                cells.append("[[ ]]")
            else:
                cells.append(shift_year(text))
        out.append(cells)
    return out


def _carried_paragraph(text, fields, sbu_label, year):
    """A paragraph of the previous order for the new one: a sentence by which
    the Commission approves a head is rewritten from the decision recorded
    for that head; any other wording is carried over with its years moved on
    and its figures highlighted."""
    m = DECISION_SENTENCE.search(text)
    if m and fields:
        field = _lookup_field(fields, m.group("label"))
        if field and field.get("excluded"):
            return []  # the decision on a head removed from the order
        if field:
            lead = CLAUSE_START_PAT.match(text)
            body = [t for t in _field_paragraphs(field, sbu_label, year) if not t.startswith("The MYT Order approved")]
            if body:
                body[0] = (lead.group(0) if lead else "") + body[0]
                return body
    return [_mark_figures(shift_year(text))]


ABBREVIATION_END = re.compile(r'(?<![A-Za-z])(?:Rs|No|Nos|Sl|Dr|Sri|Smt|viz|i\.e|e\.g)\.$')


def _join_hyphen_breaks(blocks):
    """A sentence that wraps at a hyphen ("SBU-" / "G of KSEB Ltd ...") or
    just after an abbreviation ("Rs." / "189.46 Cr") was stored as several
    blocks in layouts read before this was handled; join them back."""
    out = []
    for b in blocks:
        prev = out[-1] if out else None
        broken = (prev is not None and prev["type"] in ("para", "heading") and b["type"] in ("para", "heading")
                  and not CLAUSE_START_PAT.match(b["text"])
                  and (prev["text"].endswith("-") or ABBREVIATION_END.search(prev["text"])))
        if broken:
            glue = "" if prev["text"].endswith("-") else " "
            # keeps the first part's print style (order_style sets it the same way)
            out[-1] = {"type": "para", "text": prev["text"] + glue + b["text"], "style": prev.get("style")}
        else:
            out.append(b)
    return out


def _sibling_comparisons(data):
    """The comparison for each SBU made from the same three documents and
    year, so one download fills every SBU chapter that has been compared."""
    import comparison as cmp
    found = {}
    for entry in cmp.list_comparisons():
        other = cmp.load_comparison(entry["comparison_id"])
        if not other or other.get("input_errors"):
            continue
        if all(other.get(k) == data.get(k) for k in ("tuo_doc_id", "arr_doc_id", "petition_doc_id", "target_year")):
            found[other.get("sbu", "G")] = other
    found[data.get("sbu", "G")] = data
    return found


def build_full_docx(data):
    """The whole order as .docx bytes, laid out like the previous order."""
    tuo = storage.load_data(data["tuo_doc_id"])
    sections = [(k, s) for k, s in (tuo.get("sbus") or {}).items() if "error" not in s]
    if not sections or any("blocks" not in s for _, s in sections):
        raise LookupError("The previous order hasn't been re-read for layout yet - wait for its "
                          "'Updating' status in the Documents tab to clear, then try again.")
    sections.sort(key=lambda ks: ks[1]["pages"][0])
    for _, sec in sections:
        sec["blocks"] = _join_hyphen_breaks(sec["blocks"])
    year = data["target_year"]
    siblings = _sibling_comparisons(data)
    names = {"G": "SBU-G", "T": "SBU-T", "D": "SBU-D"}

    import order_consolidated as consolidated
    import order_style as house

    # set the way the previous order is set (see order_style): A4, Arial,
    # its headings, hanging clause numbers and tables
    doc = house.new_document()
    notice = doc.add_paragraph()
    house.write_runs(notice, f"DRAFT TRUING UP ORDER FOR {year} - laid out like the previous order "
                             f"({tuo.get('filename')}). Yellow marks what needs checking: figures and dates carried "
                             f"over from the previous order's wording, a [ ] where no figure has been supplied, and "
                             f"[bracketed] text where the Commission's decision or reasoning is still to be written. "
                             f"Chapters for {', '.join(names[s] for s in sorted(siblings))} are filled from the "
                             f"reviewed comparison(s), and the tables combining all three business units (Chapter 1's "
                             f"summary, Chapter 7) from the sum of them - complete only when all three units have been "
                             f"compared; other chapters keep the layout only.", size=9, bold=True)

    for n, (key, sec) in enumerate(sections):
        fields = _fields_by_key(siblings.get(key))
        sbu_label = names.get(key, "")
        if n:
            doc.add_page_break()
        seen_text = False  # the chapter's title lines come before any paragraph
        for block in sec["blocks"]:
            style = block.get("style") or {}
            if block["type"] == "heading":
                text = shift_year(block["text"])
                centred = re.match(r'CHAPTER', text, re.I) or \
                    (not seen_text and (style.get("x0") or 0) - house.LEFT_MARGIN_PT > 25)
                if centred:
                    house.chapter_heading(doc, text)
                else:
                    house.heading(doc, text, style)
            elif block["type"] == "para":
                seen_text = True
                for k, text in enumerate(_carried_paragraph(block["text"], fields, sbu_label, year)):
                    # a decision rewritten into several sentences: the later
                    # ones run on under the clause, at its hanging indent
                    house.paragraph(doc, text, style if k == 0 else {**style, "x0": style.get("indent")})
            else:
                table = sec[block["bucket"]][block["index"]]
                header = table.get("header") or []
                if not header:
                    continue
                house.caption(doc, table.get("table_no"), shift_year(table.get("title") or ""))
                # a table combining the three units (Table 1.1, Chapter 7) is
                # filled from all three comparisons; any other from its own
                rows = consolidated.table_rows(
                    table, siblings, effective_approved, shift_year,
                    unit_rows=lambda t, unit: _table_rows(t, _fields_by_key(siblings.get(unit))))
                if rows is None:
                    rows = _table_rows(table, fields)
                house.table(doc, header, rows, table.get("layout"), table.get("unit_row"), shift_year)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
