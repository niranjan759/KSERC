import pdfplumber, re

UNIT_PAT = re.compile(r'^\(?(Rs\.?\s*(Cr|Crore|Lakh)?|MU|kWh|Rs/kWh|Rs\.?/unit|%|MW|Nos?\.?)\)?\.?$', re.I)
CHAPTER_PAT = re.compile(r'^\s*CHAPTER\s*[–—-]?\s*(\d+)\s*[:–—-]?\s*(.*)$', re.I)

# Matches every table-numbering convention seen so far:
#   "Table 2.1" / "Table-2.1"        -> prefix="",  num="2.1"
#   "Table- G 1" / "Table-G7"        -> prefix="G", num="1" / "7"
#   "Table G11-..." (title same line)-> prefix="G", num="11", trailing="-..."
#   "Table-T 2: ..."                 -> prefix="T", num="2", trailing=": ..."
#   "Table V(3)" / "Table - 3"       -> prefix="V" or "", num="3"
#   "Table – G2: ..." / "Table — 3" -> en-dash/em-dash used as the separator
#     instead of an ASCII hyphen (common in Word-generated PDFs) and/or the
#     number wrapped in parentheses. Both dash classes and optional parens
#     must be accepted or these markers silently fail to match, which was the
#     root cause of "Table None" fragments swallowing real tables (G2/G3/G4)
#     into whatever table happened to be open when pdfplumber hit that row.
#   "Table :4.61"                    -> prefix="", num="4.61" (ARR order uses a
#     bare colon, not a dash, right before the number on some tables)
DASH = r'[-–—]'
SEP = r'[-–—:]'
TABLE_MARKER_PAT = re.compile(
    r'^[\s"“‘\'”’]*Table\s*' + SEP + r'?\s*([A-Za-z]{0,2})\s*' + SEP +
    r'?\s*\(?\s*(\d+(?:\.\d+)?)\s*\)?\s*[:\-–—]?\s*(.*)$',
    re.I
)


def is_unit_header_row(row):
    non_empty = [c for c in row if c and str(c).strip()]
    if not non_empty:
        return False
    return all(UNIT_PAT.match(str(c).strip()) for c in non_empty)


# Narrative paragraphs (e.g. "2.3.1 From the table, it may kindly be seen...")
# sit directly below a real table on the page and pdfplumber sometimes folds
# them into the SAME table object as extra one-cell rows (confirmed on the
# Petition PDF's Table G3: the whole following paragraph, sentence by
# sentence, ends up appended to G3's data_rows). Every such paragraph in
# these documents opens with the standard clause-numbering convention
# ("2.3.1 ...", "2.5.10 ...", "2.13.1 ..."), which a real data row never does,
# so it's a reliable, low-risk split point.
PARA_NUM_PAT = re.compile(r'^\d+\.\d+(?:\.\d+)?\s')
# same clause numbering, but landing in its OWN cell with the paragraph text
# in the next cell (e.g. Table G11's trailing prose: ['2.11.1', 'The Hon...'])
CLAUSE_NUM_ONLY_PAT = re.compile(r'^\d+\.\d+(?:\.\d+)?$')


def is_prose_row(row):
    non_empty = [c for c in row if c and str(c).strip()]
    if len(non_empty) == 1:
        return bool(PARA_NUM_PAT.match(non_empty[0].strip()))
    if len(non_empty) == 2:
        return bool(CLAUSE_NUM_ONLY_PAT.match(non_empty[0].strip()))
    return False


def is_row_label_empty(row):
    return not (row and row[0] and str(row[0]).strip())


NUMERIC_CELL_PAT = re.compile(r'^[+-]?[\d,]+(\.\d+)?%?$')


def looks_like_header_continuation_row(row):
    """A leading-blank-column row (see is_row_label_empty) is only safe to merge
    into the header text when it ALSO contains no cell that looks like an actual
    number. Column 0 being blank is not enough on its own: some tables put the
    real row label in column 1, not column 0 (e.g. Table 2.7's data rows are
    ['', '1', '', '', 'Employee Cost', '', '206.08', ...] — blank col0, but very
    much real data, not more header text). Without the numeric check, rows like
    that get silently merged into the header, destroying the actual figures
    while leaving the header/data column counts still matching (so
    needs_review never catches it)."""
    non_empty = [c for c in row if c and str(c).strip()]
    if not non_empty or not is_row_label_empty(row):
        return False
    return not any(NUMERIC_CELL_PAT.match(str(c).strip()) for c in non_empty)


def join_cell(cell):
    if cell is None:
        return None
    return re.sub(r'\s+', ' ', cell.replace('\n', ' ')).strip()


def _normalize_dashes(text):
    return re.sub(r'[–—]', '-', text)


def find_chapter_by_keyword(pdf, patterns):
    """Scan the whole doc for CHAPTER heading lines; return (start_page, end_page)
    [0-indexed, end exclusive] for the first chapter whose heading text matches
    one of `patterns` (compiled regexes, tried in priority order). Matching by
    keyword, not by chapter number, since chapter numbering meaning can differ
    across document types.

    `patterns` is tried as an ordered list: the whole document is scanned for
    the first pattern before falling back to the next one. This matters
    because the ARR order's SBU-G chapter ("Chapter-4, ARR&ERC of SBU-G") never
    spells out "GENERATION" in its heading the way the Truing Up Order and the
    Petition both do ("...STRATEGIC BUSINESS UNIT GENERATION (SBU-G)") — so a
    single literal "GENERATION" keyword silently finds nothing on that document
    type. Falling back to a looser "SBU-G" pattern only when "GENERATION" isn't
    found anywhere avoids that looser pattern accidentally matching an earlier,
    unrelated chapter that happens to mention "SBU-G" in passing (e.g. Chapter-1
    introductions list all three SBUs by name).

    The chapter's descriptive title is not always on the same line as the
    "CHAPTER-N" marker — some documents put "CHAPTER-2" on its own line and
    the title ("...GENERATION (SBU-G)") on the next 1-2 lines. So the keyword
    search window includes a few lines after the marker line, not just it."""
    if not isinstance(patterns, (list, tuple)):
        patterns = [patterns]

    chapters = []
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        lines = text.split("\n")
        for li, line in enumerate(lines[:4]):
            m = CHAPTER_PAT.match(line.strip())
            if m:
                # pull in up to 3 following lines as part of the heading window,
                # in case the title wraps onto separate lines
                window = " ".join(l.strip() for l in lines[li:li + 4])
                chapters.append({"start_page": i, "heading": window})
                break
    for idx, ch in enumerate(chapters):
        ch["end_page"] = chapters[idx + 1]["start_page"] if idx + 1 < len(chapters) else len(pdf.pages)

    for pattern in patterns:
        for ch in chapters:
            if pattern.search(_normalize_dashes(ch["heading"])):
                return ch["start_page"], ch["end_page"], ch["heading"]
    return None, None, None


# Tried in order: plain "GENERATION" first (how the Truing Up Order and the
# Petition both title the SBU-G chapter), falling back to the narrower
# "SBU-G" abbreviation only if no chapter anywhere spells out "GENERATION"
# (how the ARR order titles it: "Chapter-4, ARR&ERC of SBU-G").
SBU_G_CHAPTER_PATTERNS = [
    re.compile(r'GENERATION', re.I),
    re.compile(r'SBU\s*-\s*G\b', re.I),
]


def row_as_marker(row):
    """If a data row is actually an embedded table title (pdfplumber merged
    two physically-separate tables into one object), return its marker match."""
    non_empty = [c for c in row if c and str(c).strip()]
    if len(non_empty) != 1:
        return None
    return TABLE_MARKER_PAT.match(non_empty[0].strip())


def _looks_like_marker(prefix, num):
    return f"{prefix}{num}", bool(re.match(r'^\d+\.\d+$', num)) or bool(prefix and prefix.upper() != 'V')


def _column_edges(table):
    """X-coordinate boundaries for a pdfplumber Table's columns, taken from
    its first row's cells. Returns None if that row has any merged/missing
    cell, since a partial boundary set is worse than none (see caller)."""
    if not table.rows or not table.rows[0].cells:
        return None
    cells = table.rows[0].cells
    if any(c is None for c in cells):
        return None
    return [cells[0][0]] + [c[2] for c in cells]


def _reconstruct_orphan_row(page, line, column_edges):
    """Split a raw text line back into per-column cell strings using column
    x-boundaries borrowed from a neighboring table (see
    collect_orphan_continuation_rows). Buckets each word by its horizontal
    center, not its left edge, since a word can straddle a column boundary
    by a point or two in these PDFs."""
    words = [w for w in page.extract_words()
             if w["top"] >= line["top"] - 1 and w["bottom"] <= line["bottom"] + 1]
    if not words:
        return None
    cells = [[] for _ in range(len(column_edges) - 1)]
    for w in words:
        center = (w["x0"] + w["x1"]) / 2
        idx = len(cells) - 1
        for ci in range(len(cells)):
            if center < column_edges[ci + 1]:
                idx = ci
                break
        cells[idx].append(w["text"])
    return [(" ".join(c).strip() or None) for c in cells]


def collect_orphan_continuation_rows(page, open_table, tables):
    """A table continuing from the previous page can lose its very first
    row entirely: pdfplumber's find_tables() anchors a table's bbox to the
    ruling lines/text alignment it detects on THIS page, and a continuation
    row sitting just above that bbox - no repeated header, no border above
    it, nothing that looks like a table edge to pdfplumber - never gets
    included in any table object on the page. It doesn't show up
    mis-attached to the wrong table either; it's simply absent from
    t.extract() for every table pdfplumber finds, so the existing
    segment/marker logic downstream never sees it at all (confirmed: on the
    2024-25 Truing Up Order, Table 2.2's "Interest & Finance Charges" row -
    the first row of the table's continuation onto the next page - is
    present in page.extract_text_lines() but silently missing from every
    table pdfplumber extracts on that page, with no needs_review signal
    since it's a missing row, not a malformed one).

    Reconstruct any such row from the raw text sitting immediately above
    this page's first table, splitting it into cells using that SAME
    table's own column x-boundaries (same table, same columns, so its
    boundaries apply to the row that continues it)."""
    if open_table is None or not tables:
        return []
    first_table = min(tables, key=lambda t: t.bbox[1])
    column_edges = _column_edges(first_table)
    if column_edges is None or len(column_edges) - 1 != len(open_table["header"]):
        return []

    orphan_rows = []
    for line in page.extract_text_lines():
        if line["bottom"] >= first_table.bbox[1]:
            continue
        # Only trust lines immediately above the table - a genuine orphaned
        # continuation row sits right at its edge. Anything further up the
        # page is more likely a running header/footer, not table data.
        if first_table.bbox[1] - line["bottom"] > 20:
            continue
        text = line["text"].strip()
        if not text or TABLE_MARKER_PAT.match(text) or CHAPTER_PAT.match(text):
            continue
        row = _reconstruct_orphan_row(page, line, column_edges)
        if row and any(c and NUMERIC_CELL_PAT.match(c.replace(" ", "").replace(",", "")) for c in row):
            orphan_rows.append(row)
    return orphan_rows


def extract_section(pdf_path, chapter_patterns=SBU_G_CHAPTER_PATTERNS):
    results = []
    reference_tables = []
    unclassified_fragments = []
    open_table = None
    open_is_order = True
    used_table_numbers = set()

    def close_open():
        nonlocal open_table
        if open_table is not None:
            if open_table["table_no"] is None:
                unclassified_fragments.append(open_table)
            else:
                (results if open_is_order else reference_tables).append(open_table)
            open_table = None

    with pdfplumber.open(pdf_path) as pdf:
        start, end, heading = find_chapter_by_keyword(pdf, chapter_patterns)
        if start is None:
            return {"error": "No SBU-G chapter heading found in this document"}

        for pnum in range(start, end):
            page = pdf.pages[pnum]

            markers = []
            for line in page.extract_text_lines():
                mm = TABLE_MARKER_PAT.match(line["text"].strip())
                if mm:
                    prefix, num, trailing = mm.group(1).upper(), mm.group(2), mm.group(3).strip()
                    table_no, is_order = _looks_like_marker(prefix, num)
                    markers.append((line["top"], table_no, is_order, trailing))

            tables = page.find_tables()

            orphan_rows = collect_orphan_continuation_rows(page, open_table, tables)
            if orphan_rows:
                open_table["data_rows"].extend(orphan_rows)
                if (pnum + 1) not in open_table["pages"]:
                    open_table["pages"].append(pnum + 1)

            for t in tables:
                raw = t.extract()
                rows = [[join_cell(c) for c in r] for r in raw]
                if not rows:
                    continue

                # --- split out any embedded table titles or trailing prose hiding inside this raw table ---
                segments = [[]]
                seg_markers = [None]
                seg_force_new = [False]
                for r in rows:
                    mm = row_as_marker(r)
                    if mm:
                        prefix, num, trailing = mm.group(1).upper(), mm.group(2), mm.group(3).strip()
                        table_no, is_order = _looks_like_marker(prefix, num)
                        segments.append([])
                        seg_markers.append((table_no, is_order, trailing))
                        seg_force_new.append(True)
                    elif is_prose_row(r):
                        # a narrative paragraph starting right where the real table ends —
                        # split it into its own segment so it lands in unclassified_fragments
                        # instead of corrupting this table's data_rows (see is_prose_row).
                        # This must fire even when it's the very first row of a brand new
                        # raw table object (segments[-1] still empty): pdfplumber often
                        # returns a whole trailing paragraph as its OWN table object, and
                        # without an explicit (None, None, None) marker tuple here, it falls
                        # through to the generic "nearest preceding Table-marker" lookup,
                        # which wrongly re-attaches it to the real table above it as a
                        # continuation (confirmed on the Petition's Table G3).
                        segments.append([r])
                        seg_markers.append((None, None, None))
                        seg_force_new.append(True)
                    else:
                        segments[-1].append(r)

                for seg_idx, seg_rows in enumerate(segments):
                    if not seg_rows:
                        continue
                    table_top = t.bbox[1]
                    if seg_markers[seg_idx] is not None:
                        marker_no, m_is_order, trailing_title = seg_markers[seg_idx]
                        marker_is_explicit = True
                    else:
                        candidates = [m for m in markers if m[0] < table_top]
                        if candidates:
                            m_top, marker_no, m_is_order, trailing_title = max(candidates, key=lambda m: m[0])
                        else:
                            marker_no, m_is_order, trailing_title = None, None, None
                        marker_is_explicit = False

                    # a "nearest preceding Table-heading text line" guess (not a marker
                    # embedded in this row) is only trusted as a continuation of the
                    # currently open table when the row shape actually matches it too.
                    # Without that check, a tiny stray fragment with no marker of its own —
                    # e.g. pdfplumber returning a wrapped header's overflow words as its own
                    # one-cell table object — gets its marker guessed as "nearest Table
                    # line", which is often the SAME table that's still open, wrongly
                    # re-attaching it as a continuation just because no closer marker exists
                    # (confirmed on the Petition's Table G4/G8 tail fragments).
                    same_marker_as_open = (open_table is not None) and (marker_no is not None) and \
                                          (marker_no == open_table["table_no"]) and \
                                          (marker_is_explicit or len(seg_rows[0]) == len(open_table["header"]))
                    no_marker_continuation = (open_table is not None) and (marker_no is None) and \
                                              not seg_force_new[seg_idx] and \
                                              (len(seg_rows[0]) == len(open_table["header"]))
                    is_continuation = same_marker_as_open or no_marker_continuation

                    # a guessed marker that names a table number ALREADY SEEN — whether
                    # still open or long since closed — but that failed the continuation
                    # check above, is untrustworthy as a brand new table's number too.
                    # Table numbers don't repeat, so a fragment that only "matches" by
                    # being nearest to a marker line it walked past (its real table may
                    # have closed pages ago) is almost certainly more of the same orphaned
                    # trailing noise (e.g. G4/G8's tail fragments, or Table 2.7's own
                    # wrapped-header overflow), not a genuine second occurrence of that
                    # number. Discard it so it falls through to unclassified_fragments
                    # instead of opening a bogus duplicate.
                    if not marker_is_explicit and not is_continuation and marker_no in used_table_numbers:
                        marker_no, m_is_order, trailing_title = None, None, None

                    if is_continuation:
                        if seg_rows[0] == open_table["header"] or (open_table.get("unit_row") and seg_rows[0] == open_table["unit_row"]):
                            data = seg_rows[1:]
                        else:
                            data = seg_rows
                        open_table["data_rows"].extend(data)
                        if (pnum + 1) not in open_table["pages"]:
                            open_table["pages"].append(pnum + 1)
                        continue

                    close_open()

                    header = list(seg_rows[0])
                    data_start = 1

                    # an embedded section heading: pdfplumber sometimes folds a table's
                    # descriptive title into its own bounding box as a one-cell first row,
                    # leaving the REAL header on the next row — confirmed both on
                    # marker-less tables (the Petition's "Normative O&M cost allowable..."
                    # and "SBU-G: O & M for Existing stations") and on tables that DO have a
                    # resolved marker (ARR's "Table 4.17": row 0 is just "O&M cost of SBU-G
                    # (Provisional) (Rs. Cr)", row 1 is the real "Year / 2022-23 / ..."
                    # header) — so this must run regardless of whether marker_no resolved.
                    # A one-cell first row that isn't a clause-numbered paragraph opener
                    # (that's prose, handled above) and is followed by a genuine
                    # multi-column row is reliably this case — every real header in these
                    # documents has more than one populated column.
                    inferred_title = None
                    if len(seg_rows) > 1:
                        first_non_empty = [c for c in header if c and str(c).strip()]
                        next_non_empty = [c for c in seg_rows[1] if c and str(c).strip()]
                        if len(first_non_empty) == 1 and len(next_non_empty) > 1 and \
                                not PARA_NUM_PAT.match(first_non_empty[0].strip()):
                            inferred_title = first_non_empty[0]
                            header = list(seg_rows[1])
                            data_start = 2

                    unit_row = None
                    # merge any further leading "header continuation" rows into the header
                    # itself — rows with a blank column 0 and no numeric-looking cell
                    # anywhere (see looks_like_header_continuation_row) that aren't the
                    # units row. Multi-line/merged header cells in the source (e.g. "KSERC
                    # approved Aux Generation" split across three physical lines, each
                    # its own pdfplumber row) otherwise end up misfiled as short,
                    # column-misaligned "data rows" instead of header text — confirmed on
                    # the Petition's Table G4, capped at 5 rows as a sanity bound.
                    merges = 0
                    while data_start < len(seg_rows) and merges < 5 and \
                            looks_like_header_continuation_row(seg_rows[data_start]) and not is_unit_header_row(seg_rows[data_start]):
                        cont = seg_rows[data_start]
                        for ci, cell in enumerate(cont):
                            if ci < len(header) and cell and str(cell).strip():
                                header[ci] = f"{header[ci]} {cell}".strip() if (header[ci] and str(header[ci]).strip()) else cell
                        data_start += 1
                        merges += 1

                    if data_start < len(seg_rows) and is_unit_header_row(seg_rows[data_start]):
                        unit_row = seg_rows[data_start]
                        data_start += 1

                    title = trailing_title if trailing_title else inferred_title
                    if not title and marker_no:
                        lines_all = page.extract_text_lines()
                        for i, l in enumerate(lines_all):
                            mm2 = TABLE_MARKER_PAT.match(l["text"].strip())
                            if mm2:
                                p2, n2, tr2 = mm2.group(1).upper(), mm2.group(2), mm2.group(3).strip()
                                t2, _ = _looks_like_marker(p2, n2)
                                if t2 == marker_no:
                                    title = tr2 if tr2 else (lines_all[i+1]["text"].strip() if i+1 < len(lines_all) else None)
                                    break

                    open_table = {
                        "table_no": marker_no,
                        "title": title,
                        "pages": [pnum + 1],
                        "header": header,
                        "unit_row": unit_row,
                        "data_rows": seg_rows[data_start:]
                    }
                    open_is_order = bool(m_is_order) if marker_no else True
                    if marker_no is not None:
                        used_table_numbers.add(marker_no)

        close_open()

    def needs_review(t):
        hlen = len(t["header"])
        return any(r for r in t["data_rows"] if len(r) != hlen)

    for bucket in (results, reference_tables, unclassified_fragments):
        for t in bucket:
            t["needs_review"] = needs_review(t)

    return {"order_tables": results, "reference_tables": reference_tables,
            "unclassified_fragments": unclassified_fragments,
            "chapter_heading": heading, "pages": [start + 1, end]}


if __name__ == "__main__":
    import json, sys
    pdf_files = sys.argv[1:] or [
        "/mnt/user-data/uploads/Truing_Up_Order_23-24.pdf",
        "/mnt/user-data/uploads/2023_-24_petition_by_ksebl.pdf",
    ]
    all_out = {}
    for f in pdf_files:
        name = f.split("/")[-1].split("\\")[-1]
        out = extract_section(f)
        all_out[name] = out
        print(f"\n=========== {name} ===========")
        if "error" in out:
            print(out["error"])
            continue
        print(f"Chapter heading: {out['chapter_heading']}  | pages {out['pages'][0]}-{out['pages'][1]}")
        print(f"SBU-G order tables found: {len(out['order_tables'])}")
        for t in out["order_tables"]:
            flag = "  <-- NEEDS REVIEW" if t["needs_review"] else ""
            print(f"  Table {t['table_no']} | pages {t['pages']} | {t['title']}{flag}")
        print(f"Reference tables excluded: {len(out['reference_tables'])}")
        for t in out["reference_tables"]:
            print(f"  Table {t['table_no']} | pages {t['pages']} | {t['title']}")
        print(f"Unclassified fragments: {len(out['unclassified_fragments'])}")
        for t in out["unclassified_fragments"]:
            preview = (t["header"][0] or "")[:60] if t["header"] else ""
            print(f"  pages {t['pages']} | {preview}")

    with open("sbu_g_extract.json", "w") as f:
        json.dump(all_out, f, indent=2)
