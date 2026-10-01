import pdfplumber, re

UNIT_PAT = re.compile(r'^\(?(Rs\.?\s*(Cr|Crore|Lakh)?|MU|kWh|Rs/kWh|Rs\.?/unit|%|MW|Nos?\.?)\)?\.?$', re.I)
ANNEXURE_PAT = re.compile(r'^\s*ANNEXURES?.{0,60}$', re.I)
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
    non_empty = [str(c).strip() for c in row if c and str(c).strip()]
    if len(non_empty) == 1:
        return bool(PARA_NUM_PAT.match(non_empty[0]))
    if len(non_empty) == 2:
        return bool(CLAUSE_NUM_ONLY_PAT.match(non_empty[0]))
    # A paragraph that pdfplumber split across several cells: a clause
    # number, then only words - no figure anywhere - adding up to a
    # sentence ("6.267 | The Non-Tariff income claimed | by KSEB | Ltd for
    # | ...", ARR Table 6.164; "2.13 | Amortisation of intangible assets |
    # towards | software development | cost", Petition 2023-24 G13).
    # Became visible once page breaks were bridged: these used to be cut
    # off by an unrelated table closing first.
    if len(non_empty) >= 3 and CLAUSE_NUM_ONLY_PAT.match(non_empty[0]):
        rest = non_empty[1:]
        if not any(NUMERIC_CELL_PAT.match(c.replace(" ", "")) for c in rest) and sum(len(c) for c in rest) > 40:
            return True
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


def _cell_lines(chars, bbox, tol=1.5):
    """Text lines inside one cell, grouped by vertical position with a
    tighter tolerance than pdfplumber's default (3pt), which is loose
    enough to merge two overlapping lines into one."""
    x0, top, x1, bottom = bbox
    inside = sorted(
        (c for c in chars
         if x0 <= (c["x0"] + c["x1"]) / 2 <= x1 and top <= (c["top"] + c["bottom"]) / 2 <= bottom),
        key=lambda c: (c["top"], c["x0"]))
    # lines are formed from visible characters only - a stray space glyph at
    # an odd height would otherwise count as a "line" of its own - but the
    # space glyphs are kept for the text, or words run together ("NLCTPSII")
    lines = []
    for c in inside:
        if not c["text"].strip():
            continue
        for ln in lines:
            if abs(ln["top"] - c["top"]) <= tol:
                ln["bottom"] = max(ln["bottom"], c["bottom"])
                break
        else:
            lines.append({"top": c["top"], "bottom": c["bottom"]})
    for ln in lines:
        ln["chars"] = [c for c in inside if abs(c["top"] - ln["top"]) <= tol and c["text"].strip()]
        members = [c for c in inside if abs(c["top"] - ln["top"]) <= tol]
        ln["text"] = pdfplumber.utils.extract_text(members).strip()
    return lines


def fix_overflow_cells(page, table, rows):
    """Undo text that has spilled from one row's cell into the next row's.

    When a wrapped label overflows its cell (the source PDF draws it past
    the row border), its last word lands inside the next row's cell at
    almost the same height as that row's own text, and pdfplumber's
    default line grouping interleaves the two character by character -
    confirmed on Truing Up Order 2023-24 Table 3.3/3.24 (SBU-T), where
    "Edamon - Kochi line compensation" came out as "TErduasmt on - Kochi
    line compensation" ("Trust", from "Additional contribution to Master
    Trust" above, woven into "Edamon"), and "ARR" as "AAvRaRil ability".

    Two lines of genuine text in one cell never overlap vertically - line
    spacing keeps them apart - so a cell with two vertically overlapping
    lines is the signal. The upper line is the foreign one (it came down
    from the row above): it's moved back onto the end of the same
    column's cell in the previous row, and the rest stays. Cells without
    overlapping lines are left exactly as pdfplumber extracted them."""
    x0, top, x1, bottom = table.bbox
    chars = [c for c in page.chars if x0 <= c["x0"] and c["x1"] <= x1 and top <= c["top"] and c["bottom"] <= bottom]
    for ri, trow in enumerate(table.rows):
        if ri >= len(rows):
            break
        if ri == 0:
            continue  # no row above to give the text back to
        for ci, bbox in enumerate(trow.cells):
            if bbox is None or ci >= len(rows[ri]):
                continue
            lines = _cell_lines(chars, bbox)
            if len(lines) < 2:
                continue
            upper, lower = lines[0], lines[1]
            if lower["top"] >= upper["bottom"] - 1:
                continue  # stacked normally, no overlap
            # a superscript / footnote mark ("Availability*") also sits a
            # little off its line - but it's short and in a smaller font;
            # spilled-over text is a whole word at body size
            size = lambda ln: sum(c["size"] for c in ln["chars"]) / len(ln["chars"])
            if len(upper["text"]) < 3 or abs(size(upper) - size(lower)) > 0.15 * size(lower):
                continue
            # Only move label text. Every confirmed overflow was words
            # ("Trust", "compensation", "Cr)"); applying this to numbers
            # was checked across all five documents and was wrong every
            # time - pdfplumber sometimes stacks two rows' figures in one
            # cell with a slight overlap (Petition 2023-24 Table D2, ARR
            # Table 6.25), and those must stay where they are.
            if re.search(r'\d', upper["text"]) or not re.search(r'[A-Za-z]', upper["text"]):
                continue
            if not lower["text"]:
                continue
            rows[ri][ci] = " ".join(ln["text"] for ln in lines[1:]) or None
            if ri > 0 and ci < len(rows[ri - 1]) and rows[ri - 1][ci]:
                rows[ri - 1][ci] = f"{rows[ri - 1][ci]} {upper['text']}"
    return rows


def join_cell(cell):
    if cell is None:
        return None
    return re.sub(r'\s+', ' ', cell.replace('\n', ' ')).strip()


def _normalize_dashes(text):
    return re.sub(r'[–—]', '-', text)


def list_chapters(pdf):
    """Every chapter in the document as {start_page, end_page, heading}
    [0-indexed, end exclusive]. Scans the whole document once; callers that
    need several SBUs from the same PDF should reuse the result.

    The chapter's descriptive title is not always on the same line as the
    "CHAPTER-N" marker — some documents put "CHAPTER-2" on its own line and
    the title ("...GENERATION (SBU-G)") on the next 1-2 lines. So the heading
    window includes a few lines after the marker line, not just it.

    Chapter numbers must increase: a page that happens to START with prose
    like "Chapter-3 of this order is extracted below" (ARR 2022-27, page 176,
    inside Chapter 5 / SBU-T) otherwise reads as a new chapter and cuts the
    real one short - SBU-T would have ended at page 175, losing Table 5.17
    onward."""
    chapters = []
    last_num = 0
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        lines = text.split("\n")
        for li, line in enumerate(lines[:4]):
            m = CHAPTER_PAT.match(line.strip())
            if m:
                num = int(m.group(1))
                if num > last_num:
                    last_num = num
                    window = " ".join(l.strip() for l in lines[li:li + 4])
                    chapters.append({"start_page": i, "heading": window, "number": str(num)})
                break
    # Annexures follow the last chapter and have no "CHAPTER-N" marker
    # (Truing Up Order 2024-25: "Annexures", p.232); the first page after
    # the last chapter's start that opens with an ANNEXURE heading begins them
    first_after = chapters[-1]["start_page"] + 1 if chapters else 0
    for i in range(first_after, len(pdf.pages)):
        lines = (pdf.pages[i].extract_text() or "").split("\n")
        for li, line in enumerate(lines[:4]):
            if ANNEXURE_PAT.match(line.strip()):
                chapters.append({"start_page": i, "number": "A",
                                 "heading": " ".join(l.strip() for l in lines[li:li + 4])})
                break
        else:
            continue
        break
    for idx, ch in enumerate(chapters):
        ch["end_page"] = chapters[idx + 1]["start_page"] if idx + 1 < len(chapters) else len(pdf.pages)
    return chapters


SBU_NAMES = {"G": "Generation", "T": "Transmission", "D": "Distribution"}
# Each SBU is recognised by its full name OR its code, because documents
# differ: the Truing Up Order and petition spell out "GENERATION", while the
# ARR's heading is just "ARR&ERC of SBU-G"; the petition's SBU-T heading is
# "SBU – T & SLDC" with no "Transmission" at all.
_SBU_PATS = {
    s: re.compile(rf'{name}|SBU\s*-?\s*{s}\b', re.I) for s, name in SBU_NAMES.items()
}


def find_sbu_chapter(chapters, sbu):
    """The chapter whose heading names this SBU and no other. Headings that
    name several SBUs are shared chapters, not any one SBU's - e.g. the
    Truing Up Order's "APPORTIONING THE SAME AMONG SBU-G, SBU-T AND SBU-D"
    (common expenses) or an introduction listing all three units. Falls
    back to the first heading that names this SBU at all, so an SBU chapter
    whose intro mentions another unit in passing is still found."""
    def named(ch):
        h = _normalize_dashes(ch["heading"])
        return {s for s, p in _SBU_PATS.items() if p.search(h)}
    for ch in chapters:
        if named(ch) == {sbu}:
            return ch
    for ch in chapters:
        if sbu in named(ch):
            return ch
    return None


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


def _value_column_centers(table, rows, ncols):
    """For each column, the median horizontal center of the cells that
    actually hold something in the table's data rows (rows with at least
    one number); None for columns that never do.

    Deliberately not column boundaries: these tables are full of hair-thin
    empty spacer columns (the None/'' header cells), and right-aligned
    figures sit right against a boundary, so bucketing by boundaries put
    values in the neighbouring spacer column. Only columns that really
    carry values are candidates here, so a spacer can't attract anything."""
    cols = []
    for j in range(ncols):
        boxes = []
        for ri, trow in enumerate(table.rows):
            if ri >= len(rows) or j >= len(trow.cells) or j >= len(rows[ri]):
                continue
            if not any(c and NUMERIC_CELL_PAT.match(str(c).replace(" ", "")) for c in rows[ri]):
                continue  # header / title rows don't count
            bbox = trow.cells[j]
            if bbox is not None and rows[ri][j] not in (None, ""):
                boxes.append(bbox)
        if boxes:
            centers = sorted((b[0] + b[2]) / 2 for b in boxes)
            cols.append({"center": centers[len(centers) // 2],
                         "x0": min(b[0] for b in boxes), "x1": max(b[2] for b in boxes)})
        else:
            cols.append(None)
    return cols if any(c is not None for c in cols) else None


def _nearest_column(x, cols):
    """The value column whose extent contains x; failing that, the nearest
    by center. Containment first: labels are left-aligned in wide columns,
    so a short label ("ARR") sits nearer the narrow serial column's center
    than its own column's, while still lying inside its own column."""
    live = [j for j, c in enumerate(cols) if c is not None]
    for j in live:
        if cols[j]["x0"] <= x <= cols[j]["x1"]:
            return j
    return min(live, key=lambda j: abs(cols[j]["center"] - x))


def remap_to_open_table(table, rows, open_table):
    """Re-lay a continuation page's table onto the open table's columns.

    pdfplumber sometimes renders the continuation of a table on the next
    page with a DIFFERENT number of raw columns than the table's header
    (finding #13: Petition 2024-25 Table G8 went 9 -> 6 columns across the
    page break, Table T6 8 -> 5), which the continuation check below can't
    merge because it requires matching column counts - so those rows
    silently became unclassified fragments. Each cell is instead placed in
    whichever of the open table's columns its horizontal center falls in:
    same table, same page layout, so the columns sit at the same x-positions
    even when pdfplumber splits them differently."""
    centers = open_table["_col_centers"]
    ncols = len(open_table["header"])
    out = []
    for ri, trow in enumerate(table.rows):
        if ri >= len(rows):
            break
        new = [None] * ncols
        for ci, bbox in enumerate(trow.cells):
            text = rows[ri][ci] if ci < len(rows[ri]) else None
            if bbox is None or text in (None, ""):
                continue
            k = _nearest_column((bbox[0] + bbox[2]) / 2, centers)
            new[k] = f"{new[k]} {text}" if new[k] else text
        out.append(new)
    return out


def _is_data_row(row):
    """Has a figure other than a leading clause number. A paragraph
    detected as a table row ("6.267 | The Non-Tariff income claimed | by
    KSEB | ...", ARR Table 6.164's page break) starts with a number too,
    but nothing else in it is one."""
    cells = [str(c).strip() for c in row if c and str(c).strip()]
    if cells and CLAUSE_NUM_ONLY_PAT.match(cells[0]):
        cells = cells[1:]
    return any(NUMERIC_CELL_PAT.match(c.replace(" ", "")) for c in cells)


def _strip_repeated_header(rows, header):
    """Drop leading rows of a continuation that just repeat the table's
    column headings (ARR Table 6.83 reprints "Sl No / Source / KSEB Ltd /
    Energy in MU ..." at the top of its continuation page): rows with no
    figures whose every cell already appears in the table's header text."""
    header_text = _norm_words(" ".join(str(h) for h in header if h))
    i = 0
    while i < len(rows) and not _is_data_row(rows[i]):
        cells = [str(c) for c in rows[i] if c and str(c).strip()]
        if cells and not all(_norm_words(c) in header_text for c in cells):
            break
        i += 1
    return rows[i:]


def _norm_words(s):
    return " ".join(re.sub(r'[^a-z0-9]+', ' ', s.lower()).split())


def _drop_nested_tables(tables, tol=2):
    """Discard a detected table lying entirely inside another table's area
    on the same page. pdfplumber sometimes detects part of a table a second
    time as its own tiny table - confirmed on Petition 2024-25 page 16,
    where Table G8's wrapped "ARR / Approval" column header came back as a
    separate 1-column table inside G8. Its text is already in the outer
    table, and processing it afterwards closed G8 too early, so G8's
    continuation on page 17 was lost."""
    def inside(a, b):
        return (a.bbox[0] >= b.bbox[0] - tol and a.bbox[1] >= b.bbox[1] - tol
                and a.bbox[2] <= b.bbox[2] + tol and a.bbox[3] <= b.bbox[3] + tol)
    return [t for t in tables if not any(o is not t and inside(t, o) and not inside(o, t) for o in tables)]


def _is_page_continuation(table, tables, markers, open_table, pnum):
    """This table plausibly continues the table left open on the previous
    page: it's the first table on the page, no "Table N" marker sits above
    it, the open table was last extended on the immediately preceding page,
    and the two occupy the same horizontal span."""
    if open_table is None or not open_table.get("_col_centers"):
        return False
    if table is not min(tables, key=lambda t: t.bbox[1]):
        return False
    # pages are 1-indexed, pnum is this page's 0-index: pnum means "ended on
    # the previous page"; pnum + 1 means an orphaned first row from this
    # page has already been attached to it (collect_orphan_continuation_rows)
    if open_table["pages"][-1] not in (pnum, pnum + 1):
        return False
    if any(m[0] < table.bbox[1] for m in markers):
        return False
    ox0, ox1 = open_table["_x_span"]
    x0, x1 = table.bbox[0], table.bbox[2]
    overlap = min(ox1, x1) - max(ox0, x0)
    return overlap >= 0.7 * min(ox1 - ox0, x1 - x0)


def _reconstruct_orphan_row(page, line, column_edges=None, centers=None):
    """Split a raw text line back into per-column cell strings, using either
    the open table's value-column centers (preferred - see
    _value_column_centers) or column x-boundaries borrowed from a
    neighboring table. Each word is placed by its horizontal center, not its
    left edge, since a word can straddle a column boundary by a point or two
    in these PDFs."""
    words = [w for w in page.extract_words()
             if w["top"] >= line["top"] - 1 and w["bottom"] <= line["bottom"] + 1]
    if not words:
        return None
    ncols = len(centers) if centers is not None else len(column_edges) - 1
    cells = [[] for _ in range(ncols)]
    for w in words:
        center = (w["x0"] + w["x1"]) / 2
        if centers is not None:
            idx = _nearest_column(center, centers)
        else:
            idx = ncols - 1
            for ci in range(ncols):
                if center < column_edges[ci + 1]:
                    idx = ci
                    break
        cells[idx].append(w["text"])
    return [(" ".join(c).strip() or None) for c in cells]


def collect_orphan_continuation_rows(page, open_table, tables, pnum):
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
    if open_table is None or not tables or open_table["pages"][-1] != pnum:
        return []
    first_table = min(tables, key=lambda t: t.bbox[1])
    # Prefer the open table's own column geometry: the continuation page's
    # table may be split into a different number of columns (finding #13),
    # which is exactly when its own boundaries can't be used.
    centers = open_table.get("_col_centers")
    column_edges = None
    if centers is None:
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
        # a paragraph's first line ("6.267 The Non-Tariff income claimed by
        # KSEB Ltd ...") sitting just above a table isn't a table row. Judged
        # by the words, not just the leading number: a row of pure figures
        # ("0.00 131.85 0.00") starts the same way and is real data.
        if PARA_NUM_PAT.match(text) and sum(t.isalpha() for t in text.split()) >= 5:
            continue
        row = _reconstruct_orphan_row(page, line, column_edges, centers)
        if row and _is_data_row(row):
            orphan_rows.append(row)
    return orphan_rows


def normalize_table_rows(header, rows):
    """Pad or trim every row to the table's actual column count.

    pdfplumber and page-break continuations can produce a row one cell short,
    one cell long, or with a filler column stuck in the middle. Rendering the
    raw length directly creates visibly improper tables, even when the value
    stream itself is otherwise valid. Normalizing here keeps the browser table
    aligned without losing any meaningful value to the left or right.
    """
    if not rows:
        return []
    expected = len(header) if header is not None else max(len(r) for r in rows if isinstance(r, (list, tuple)))
    if expected <= 0:
        return [list(r) if isinstance(r, (list, tuple)) else [r] for r in rows]
    out = []
    for row in rows:
        cells = list(row) if row is not None else []
        if len(cells) < expected:
            cells.extend([None] * (expected - len(cells)))
        elif len(cells) > expected:
            cells = cells[:expected]
        out.append(cells)
    return out


def chapter_label(chapter):
    """Short tab label for a chapter: its heading without the "CHAPTER-N"
    marker and the clause text that follows the title."""
    h = _normalize_dashes(chapter["heading"])
    h = re.sub(r'^\s*CHAPTER\s*\S*\s*\d+\s*[:\-]?\s*', '', h, flags=re.I)
    h = re.split(r'\s\d+\.\d*\s', h)[0].strip()
    if len(h) > 45:
        h = h[:45].rsplit(" ", 1)[0] + "…"
    n = chapter.get("number")
    return f"Annexures" if n == "A" else f"Ch.{n} {h.title()}"


def extract_all_sections(pdf_path):
    """Every chapter of the document, from a single chapter scan. SBU
    chapters are keyed "G"/"T"/"D" (what comparisons read); every other
    chapter - introduction, energy sales, common expenses, consolidated
    accounts, annexures - is keyed "C<number>" ("CA" for annexures)."""
    with pdfplumber.open(pdf_path) as pdf:
        chapters = list_chapters(pdf)
    out = {sbu: extract_section(pdf_path, sbu, chapters) for sbu in SBU_NAMES}
    sbu_starts = {s["pages"][0] for s in out.values() if "error" not in s}
    for ch in chapters:
        if ch["start_page"] + 1 in sbu_starts:
            continue
        out[f"C{ch['number']}"] = extract_chapter(pdf_path, ch)
    return out


def extract_section(pdf_path, sbu="G", chapters=None):
    with pdfplumber.open(pdf_path) as pdf:
        chapter = find_sbu_chapter(chapters if chapters is not None else list_chapters(pdf), sbu)
    if chapter is None:
        return {"error": f"No SBU-{sbu} chapter heading found in this document"}
    section = extract_chapter(pdf_path, chapter)
    section["label"] = f"SBU-{sbu} {SBU_NAMES[sbu]}"
    return section


def extract_chapter(pdf_path, chapter):
    results = []
    page_texts = []
    reference_tables = []
    unclassified_fragments = []
    open_table = None
    open_is_order = True
    used_table_numbers = set()

    def close_open():
        nonlocal open_table
        if open_table is not None:
            open_table["header"] = normalize_table_rows(open_table["header"], [open_table["header"]])[0]
            if open_table.get("unit_row") is not None:
                open_table["unit_row"] = normalize_table_rows(open_table["header"], [open_table["unit_row"]])[0]
            open_table["data_rows"] = normalize_table_rows(open_table["header"], open_table.get("data_rows", []))
            open_table.pop("_col_centers", None)
            open_table.pop("_x_span", None)
            if open_table["table_no"] is None:
                unclassified_fragments.append(open_table)
            else:
                (results if open_is_order else reference_tables).append(open_table)
            open_table = None

    with pdfplumber.open(pdf_path) as pdf:
        start, end, heading = chapter["start_page"], chapter["end_page"], chapter["heading"]

        for pnum in range(start, end):
            page = pdf.pages[pnum]
            page_texts.append({"page": pnum + 1, "text": page.extract_text() or ""})

            markers = []
            for line in page.extract_text_lines():
                mm = TABLE_MARKER_PAT.match(line["text"].strip())
                if mm:
                    prefix, num, trailing = mm.group(1).upper(), mm.group(2), mm.group(3).strip()
                    table_no, is_order = _looks_like_marker(prefix, num)
                    markers.append((line["top"], table_no, is_order, trailing))

            tables = _drop_nested_tables(page.find_tables())

            orphan_rows = collect_orphan_continuation_rows(page, open_table, tables, pnum)
            if orphan_rows:
                open_table["data_rows"].extend(orphan_rows)
                if (pnum + 1) not in open_table["pages"]:
                    open_table["pages"].append(pnum + 1)

            for t in tables:
                raw = t.extract()
                rows = fix_overflow_cells(page, t, [[join_cell(c) for c in r] for r in raw])
                if not rows:
                    continue
                table_rows = rows  # as laid out on this page, aligned with t.rows
                # A continuation page starts straight with data rows (finding
                # #5 - no repeated header). A mismatched table that opens with
                # a header-like row (no figures) is a new table whose title
                # fell at the bottom of the previous page - merging it jammed
                # its header into the previous table's columns (Petition
                # 2024-25, SBU-D power purchase tables).
                starts_with_data = _is_data_row(rows[0])
                if (len(rows[0]) != len(open_table["header"]) if open_table else False) \
                        and starts_with_data and not is_prose_row(rows[0]) \
                        and _is_page_continuation(t, tables, markers, open_table, pnum):
                    rows = remap_to_open_table(t, rows, open_table)

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
                        open_table["data_rows"].extend(_strip_repeated_header(data, open_table["header"]))
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

                    data_rows = normalize_table_rows(header, seg_rows[data_start:])
                    if unit_row is not None:
                        unit_row = normalize_table_rows(header, [unit_row])[0]
                    open_table = {
                        "table_no": marker_no,
                        "title": title,
                        "pages": [pnum + 1],
                        "header": header,
                        "unit_row": unit_row,
                        "data_rows": data_rows,
                        # page geometry, used only to merge this table's
                        # continuation on the next page; stripped on close
                        "_col_centers": _value_column_centers(t, table_rows, len(header)),
                        "_x_span": (t.bbox[0], t.bbox[2]),
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
            "chapter_heading": heading, "pages": [start + 1, end],
            "label": chapter_label(chapter), "text": page_texts}


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
