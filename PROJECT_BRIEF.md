# KSERC Truing-Up HITL Decision-Support System — Project Brief for Claude Code

## Who this is for

I'm building a Human-in-the-Loop (HITL) decision-support system for the
Kerala State Electricity Regulatory Commission (KSERC). This document
gives you full context so you don't need it re-explained — read it fully
before writing any code.

> **2026-09-28 reconciliation note**: this brief was rewritten after
> comparing an older snapshot (found in `~/Downloads/extract_sbu_g.py`,
> `PROJECT_BRIEF.md`, `sbu_g_extract_all3_verified.json`) against this
> project directory's actual current state. The Downloads snapshot is a
> strict ancestor of what's here — nothing in it is newer or better — but
> its "current phase" section had gone stale: a working backend + frontend
> already exist, and finding #10 below has partial progress that the old
> brief didn't know about. See "Current phase" and finding #10 for what's
> actually true now.

## Domain background

- Every year, KSEB (Kerala's state electricity board, legally KSEB Ltd /
  KSEBL) files a "Truing-Up Petition" — a claim reconciling what they
  actually spent against what KSERC had earlier approved (the ARR —
  Approved Annual Revenue Requirement) for that year.
- KSERC reviews this and issues a "Truing Up Order" that finalizes
  approved vs. claimed figures for that year.
- KSEB's business is split into three Strategic Business Units (SBUs):
  - **SBU-G** — Generation
  - **SBU-T** — Transmission
  - **SBU-D** — Distribution
- Each regulatory document (Petition, Truing Up Order, ARR order) is
  organized into chapters/sections by SBU, containing numbered tables
  with the actual financial figures — cost of generation, O&M expenses,
  interest & financing charges, depreciation, power purchase costs, etc.
- These PDFs are long (150–500+ pages), Word-generated (real text/table
  layer, not scanned), and each document type uses its OWN chapter
  numbering and table-naming convention — see "Key technical findings,"
  this is critical and has already caused multiple real bugs.

## The full pipeline (four stages) — what this system actually does

This is the complete requirement, clarified after earlier scoping
discussion. Build toward this, but see "Current phase" for what to
actually implement right now.

**(i) Previous Truing Up Order → schema discovery.** Input: last year's
Truing Up Order. Purpose: NOT to extract its values for their own sake,
but to learn its structure — which tables/fields exist (e.g. "Cost of
Generation of Power," "O&M Expenses," "Interest & Finance Charges") —
because that same set of fields is what needs to be pulled from THIS
year's petition. This is schema inference from a template document.

**(ii) ARR → approved budget per field.** Input: the ARR order for the
relevant control period. Purpose: extract the "approved"/"allotted"
figure for each of the fields identified in stage (i) — this is the
ceiling/benchmark each claimed figure gets compared against.

**(iii) Current Petition → claimed values + comparison + XAI.** Extract
the same fields (using the schema from stage i) from this year's
petition. On the dashboard: show ARR-approved vs. petition-claimed side
by side, compute the deviation, and for each significant deviation, show
an explanation of what likely caused it — power purchase cost swings,
rainfall/hydro reservoir levels, demand growth, fuel price changes, etc.
This is the XAI layer. "Significant" deviation threshold must be
reviewer-configurable (see "Deviation thresholds" below), not hardcoded.

**(iv) Generate the Truing Up Order.** Once the human reviewer has
verified/adjusted the values on the dashboard, auto-compile the final
Truing Up Order document from the approved data.

**The AI/system is strictly a decision-support assistant — final
judgment always belongs to the human reviewer, at every stage.**

## Current phase — what to actually build right now

Scope is narrow on purpose: **SBU-G (Generation) only**, across all three
document types (Truing Up Order, Petition, ARR). Get extraction +
field-matching + deviation display working end-to-end for SBU-G before
touching SBU-T, SBU-D, the XAI/ML layer, or order generation (stage iv).

**No AI/LLM API calls anywhere in the pipeline.** Everything must run
locally/offline with zero per-use cost. Use only open-source libraries
(pdfplumber, FastAPI, rapidfuzz, etc.).

**Status as of this rewrite:**
- Extraction script (`backend/extraction/extract_sbu_g.py`): substantially
  ahead of findings #1–9, with real (if incomplete) progress on finding
  #10 — see that finding for the current numbers.
- Backend (`backend/main.py`, `backend/storage.py`): **built**. FastAPI
  app with upload → extract → store, list/get documents, inline row edits
  + a "reviewed" flag via PATCH, and per-page PDF-to-PNG rendering
  (PyMuPDF) for the "view source page" requirement.
- Frontend (`frontend/`): **built, but only step 5's single-document
  review view** — document list, table-by-table display, presumably
  inline edit / mark-reviewed (verify against `app.js` before assuming
  more than that). **Not built**: ARR-vs-Petition side-by-side
  comparison, deviation computation/display, or the deviation-threshold
  settings panel — those are still open (see steps 4–5 below).
- Canonical field registry / matching layer (stage iii design, step 2):
  **not built at all.** No `registry`, `canonical`, `alias`, or
  `rapidfuzz` anywhere in `backend/` or `frontend/`, and `rapidfuzz` is
  not in `requirements.txt`.
- A `v2/` folder exists at the project root and is currently empty —
  purpose not yet established; ask before assuming it's a planned rewrite
  target.
- Test documents on hand now include a **fourth** document not in the
  original three: `TRUING UP ORDER 24-25.pdf` (22–37, 16 order tables, 2
  unclassified fragments per the latest extraction run) — a second year
  of Truing Up Order data. Useful once stage (i)'s schema-discovery step
  is built, since it gives a second template to check the schema against.

## Test documents (all three already analyzed and extraction-verified)

- `Truing_Up_Order_23-24.pdf` (237 pages) — SBU-G = Chapter 2, pages 19–36
- `2023_-24_petition_by_ksebl.pdf` (170 pages) — SBU-G = Chapter 2, pages 5–24
- `ARR_2022-27.pdf` (493 pages) — SBU-G = **Chapter 4**, pages 105–160
  (different chapter NUMBER than the other two documents — see finding #2)
- `TRUING UP ORDER 24-25.pdf` — a second Truing Up Order year, discovered
  in a later extraction run; not yet formally profiled the way the other
  three are documented below.

## Key technical findings (already discovered — do not rediscover these)

These are proven facts about the document formats, verified against
actual PDFs with pdfplumber across multiple debugging rounds. Each one
caused a real, confirmed bug before being found and fixed.

1. **Chapter numbering and table-naming conventions differ between ALL
   THREE document types — no two use the same convention.**
   - Truing Up Order: `Table 2.1`, `Table 2.2`, ... `Table 2.19` (decimal,
     chapter.number, SBU-G = Chapter 2).
   - Petition: `Table- G 1`, `Table-G7`, `Table G10`, `Table G11-...`
     (inconsistent spacing/hyphenation, "G" prefix, SBU-G = Chapter 2).
     Its SBU-T section uses yet another prefix: `Table-T 1`, `Table-T 2`.
   - ARR: `Table 4.1` ... `Table 4.63` (decimal, chapter.number — but
     SBU-G is **Chapter 4** here, not Chapter 2). Also has further marker
     variants within itself: `Table: 4.14` / `Table : 4.37` (colon
     separator, sometimes with a space before it), and `Table :4.61`
     (bare colon right before the number) instead of the more common
     `Table 4.1` (space) or `Table-4.10` (dash). All of these separator
     styles can appear in the SAME document, and the current regex also
     accepts en-dash/em-dash separators (`Table – G2:`, `Table — 3`) and
     an optional parenthesized number (`Table V(3)`) — both turned out to
     be common enough in these Word-generated PDFs to cause real
     mismatches when missing.
   **Never hardcode a table-numbering regex tuned to one document's
   style — always support space, dash (ASCII/en/em), colon separators,
   optional parens, with or without a 1-3 letter SBU prefix.**

2. **Chapter start/end pages AND chapter numbers differ per document —
   detect both dynamically, never hardcode either.** SBU-G is "Chapter 2"
   in the Truing Up Order (pages 19–36) and the Petition (pages 5–24),
   but "Chapter 4" in the ARR (pages 105–160). Never assume "chapter
   number 2 always means Generation."

3. **A single keyword is not enough to find the right chapter — different
   documents phrase the SBU-G heading differently.** The Truing Up
   Order's heading contains "...GENERATION (SBU-G)" and the Petition's
   contains "...SBU – GENERATION" — both match keyword "GENERATION." But
   the ARR's heading is "ARR&ERC of SBU-G" and **never contains the word
   "Generation" anywhere** — only "SBU-G" matches.
   **Design note**: the current script implements this as an *ordered
   list of regex patterns* tried against the whole document in priority
   order (`GENERATION` first, `SBU\s*-\s*G\b` as fallback), not as the
   per-SBU alias dict (`SBU_KEYWORD_ALIASES`) the original version used.
   The alias-dict version was more directly extensible to SBU-T/SBU-D
   (just add entries); the current ordered-pattern version only handles
   SBU-G today via its module-level `SBU_G_CHAPTER_PATTERNS` constant,
   with `chapter_patterns` as a function parameter for a caller to
   override. **When SBU-T/SBU-D support is added, decide explicitly
   whether to restore the per-SBU alias-dict mechanism (as this project
   was originally scoped) or keep per-SBU ordered pattern-list constants
   — don't let this drift silently.**

4. **A chapter's descriptive title is not always on the same line as its
   "CHAPTER-N" marker.** In the Truing Up Order, page 19 has "CHAPTER-2"
   on its own line, then "TRUING UP OF ACCOUNTS OF STRATEGIC BUSINESS
   UNIT" and "GENERATION (SBU-G)" on the following two lines. A keyword
   search must include a window of the next few lines after the CHAPTER
   marker line, not just that one line.

5. **Tables often span a page break with no repeated header on the
   continuation page.** pdfplumber's `find_tables()`/`extract_tables()`
   treats each page independently, so a table starting on page 19 and
   continuing on page 20 comes back as two disconnected table objects.
   Merge these by checking if a same-page table with no marker of its
   own has the same column count as the currently "open" table.

6. **Some documents quote tables verbatim from the Tariff Regulations**
   for reference (e.g. `Table V(3)`, `Table - 3`, `Table- 1`) right next
   to the order's own analytical tables, using a totally different
   numbering scheme (roman numerals, or plain single-digit numbers with
   no chapter prefix). These are NOT part of the petition's financial
   claims — exclude them into a separate `reference_tables` bucket
   instead of contaminating `order_tables`.

7. **pdfplumber sometimes merges two physically-adjacent tables into one
   table object**, so a table's title row ends up as a data row inside
   the PREVIOUS table's extracted data, corrupting both tables. Detect a
   data row that is itself a table marker/title and split at that row.

8. **Multi-line header cells** (e.g. "MYT Order\ndated\n25.06.2022") must
   be joined into one string (`\n` → space), never split into separate
   fields or rows.

9. **Full-document scans are expensive on large PDFs and must exit
   early.** The ARR is 493 pages; `extract_text()` costs ~0.15s/page, so
   scanning the whole document to find chapter boundaries took over 2
   minutes and hit a timeout. Fix: scan incrementally and stop as soon as
   BOTH the target chapter's start page AND the next chapter's start page
   (which becomes the target's end boundary) are found — don't keep
   scanning the remaining ~300+ pages after that. This cut total runtime
   for all three documents from a 2-minute timeout to 33 seconds.
   **Note**: the current script's `find_chapter_by_keyword` actually
   builds the full chapter list up front now (needed to try multiple
   ordered patterns against every chapter heading, per finding #3) rather
   than stopping at the first two boundaries found. Confirm this is still
   fast enough in practice on the 493-page ARR before assuming the
   original early-exit optimization still fully applies — it may have
   been partially traded away for the multi-pattern fallback in finding
   #3, which is a reasonable tradeoff but worth being aware of, not
   silently inherited.

10. **Petition's "Table None" fragments — partially addressed, not fully
    resolved.** Originally: the Petition PDF produced ~12 correctly-
    labeled tables (G1, G7, G10, G11, G13, etc.) plus 13 "Table None"
    fragments with no adjacent marker text found nearby. The current
    script added:
    - prose-row detection (`is_prose_row`) to split narrative paragraphs
      (e.g. "2.3.1 From the table, it may kindly be seen...") out of a
      table's `data_rows` instead of corrupting them,
    - header-continuation-row merging (`looks_like_header_continuation_row`)
      for multi-line/merged header cells that were landing as bogus
      short data rows,
    - inferred-title detection for a one-cell first row that's actually
      a table's description sitting above its real header,
    - a `used_table_numbers` check that stops a stray fragment from
      falsely reopening/continuing an already-closed table just because
      it's nearest to that table's marker line,
    - and a dedicated `unclassified_fragments` output bucket, separate
      from `order_tables` and `reference_tables`.

    This work **did** recover several real tables that the old script
    was silently merging into the wrong neighboring table under the
    wrong number — confirmed for G2, G3, G4, G8, G9, which the old
    Downloads-verified output shows as `table_no: None` entries but the
    current script correctly labels and separates.

    **However**, as of the latest extraction run (`backend/extraction/sbu_g_extract.json`),
    the *unclassified_fragments count went up, not down*, relative to
    the original baseline:

    | Document | Old baseline | Current unclassified_fragments |
    |---|---|---|
    | Truing Up Order 23-24 | 0 (not tracked as a bucket) | 5 |
    | Truing Up Order 24-25 | n/a (new doc) | 2 |
    | ARR 2022-27 | 4 | 14 |
    | Petition (2023-24) | 13 | 33 |

    This does NOT necessarily mean the fix made things worse — the new
    logic also splits previously-hidden fragments out of tables that used
    to look "clean" (e.g. prose rows that were silently sitting inside a
    real table's `data_rows` before, now correctly excluded but counted
    as their own fragment). But **this has not been re-verified against
    the source PDFs the way every fix above was**, so don't assume it's
    fine. Treat this as the immediate next task, same discipline as
    before: pull raw pdfplumber output for a sample of the current
    unclassified fragments (especially from the Petition, since 33 is a
    lot), cross-reference the actual PDF text, and determine per-fragment
    whether it's (a) truly unclassifiable noise (a sub-header, a stray
    DPR cost breakdown, etc. — fine to leave in this bucket for reviewer
    triage) or (b) a real table/row that should have gotten a marker and
    didn't (a genuine bug to fix).

11. **A page-break continuation table can lose its very first row
    entirely — fixed.** Found while building stage (i)'s schema discovery
    and verifying its output against the 2024-25 Truing Up Order: Table
    2.2 spans pages 22→23, and the continuation's first row ("Interest &
    Finance Charges") sat just above the bbox pdfplumber's `find_tables()`
    assigned to the table on page 23 — no ruling line/border above it for
    pdfplumber to anchor to. The row wasn't mis-attached anywhere; it was
    simply absent from every table object `find_tables()` returned on that
    page, so it never reached the segment/marker logic at all, and
    `needs_review` never caught it because a *missing* row doesn't break
    the header/data column-count check. This is a different failure mode
    than finding #5 (a whole continuation table returned as its own
    disconnected object) — here only the continuation's leading row goes
    missing, with the rest of the table extracted normally.

    Fixed in `extract_sbu_g.py` via `collect_orphan_continuation_rows()`:
    when a table is still open across a page boundary, check the raw text
    lines sitting immediately above (within ~20pt of) the new page's first
    detected table bbox; reconstruct any such line into cells using that
    same table's own column x-boundaries (`_column_edges` /
    `_reconstruct_orphan_row`), and prepend the result to the open table's
    `data_rows` before normal per-page processing continues. Verified: the
    recovered row's values (`189.37, 115.53, 196.15, 6.78`) match the
    source PDF exactly, and re-running extraction against all four
    documents (both Truing Up Orders, the ARR, both Petitions) afterward
    showed identical table/fragment counts to before the fix and zero
    duplicate rows — i.e. it only recovers genuinely missing rows, it
    doesn't disturb anything else. **Not yet checked**: whether this same
    silent-row-loss pattern also affects the ARR (493 pages) or Petition
    documents on a different table/page-break — the verification so far
    only confirmed no *regression*, not that every remaining page break in
    those larger documents is now fully correct. Worth a similar
    orphan-row sweep on those two before trusting the fix generalizes to
    every table shape, not just Table 2.2's 6-column layout.

12. **Cross-document field mapping must key on table TITLE, never table
    NUMBER — confirmed again, this time across documents, not just within
    one.** Found while building stage (ii) (ARR → approved budget):
    an initial version of `arr_budget.py`'s field map scoped each mapping
    entry to the literal Truing Up Order table number it was sourced from
    (e.g. "Additional contribution to Master Trust" → Table 2.19). That
    broke immediately on the 2024-25 Truing Up Order, which has fewer
    sub-tables than 2023-24's and so numbers its own equivalent summary
    table 2.16, not 2.19 — the mapping silently matched zero rows for that
    field in 2024-25, no error, just an absent result. Fixed by matching
    on the table's TITLE text ("Transfer Cost of SBU-G" appears in both
    the claimed and the KSERC-approved summary tables, every year,
    regardless of number) instead of its number. This is finding #2's
    lesson (chapter numbers shift per document) recurring one level down
    (table numbers shift per document too, even between two years of the
    SAME document type) — treat any future cross-document/cross-year
    matching the same way: title/wording patterns are stable, numbers
    are not.

13. **A page-break continuation can also fail because the continuation
    page renders the SAME table with a DIFFERENT raw column count** —
    fixed, narrowly, at the consuming-module level. Found while building
    stage (iii) on the 2024-25 petition: Table G8 ("ARR OF GENERATION
    BUSINESS UNIT (SBU-G)") closes after row "10 Others" on page 16; its
    true rows 11–13 ("ARR", "Less Non-Tariff Income", "Net ARR") land on
    page 17. Row 11 isn't inside ANY pdfplumber table object on that page
    at all (finding #11's failure mode again, in a different document) —
    but rows 12–13 land inside a table object with only 6 raw columns,
    where the original table's header has 9. `extract_sbu_g.py`'s
    continuation check requires an exact column-count match, so neither
    piece merges; all three rows end up outside `order_tables` entirely
    (not even in `unclassified_fragments`, since row 11 was never part of
    any table object to begin with).

    This time the fix was NOT made general inside `extract_sbu_g.py` —
    deriving reliable column geometry across a raw column-count mismatch
    would need broader changes to the core continuation logic, which is
    already carrying real weight (findings #1–11, verified across 5
    documents) and wasn't worth the regression risk for a pattern seen on
    one table in one document so far. Instead, `petition_claims.py` has a
    narrow, self-contained `recover_g8_tail()`: it knows Table G8's row
    order is identical across every document examined this session (see
    `G8_CANONICAL_ORDER`), so for any canonical field missing after normal
    extraction, it rescans raw text on the page(s) immediately following
    and takes the last 4 whitespace-separated tokens of a candidate line
    as [ARR Approval, Actuals, TU Sought, Difference] — trusted only when
    all 4 look numeric, and only up to the next "Table" marker line.
    Verified: recovered values for all 3 rows match the source PDF text
    exactly, and FY2023-24 (which never needed recovery) is byte-for-byte
    unchanged after this change. **If this pattern shows up on a THIRD
    document/table, that's the signal to stop patching per-module and fix
    the underlying continuation-merge logic in `extract_sbu_g.py` itself**
    — don't keep adding narrow recovery functions per table.

14. **A table can carry a constant column offset between its header and
    every data row, for the whole table, in only one of the two years —
    fixed.** Found while extending the field-mapping sweep to the Interest
    & Finance Charges sub-items: Petition Table G10 in the 2023-24
    document has ALL its values (including the row label itself) sitting
    exactly one column to the LEFT of where their header text says,
    consistently across all 8 rows — the SAME table in the 2024-25
    petition has no such offset. Different failure mode than finding
    #13's `_realign_row` (a single row's value trapped under a
    None-header padding column) — this is a whole-table shift with no
    such marker to detect it by. Fixed generally in `petition_claims.py`
    via `table_offset()`: compare where the header's own "Particulars"
    column sits against where `find_label()` actually found a given row's
    label, and apply that same difference to every column lookup on that
    row. Verified: with the correction, Table G10's five interest
    sub-items' claimed values for FY2023-24 sum to exactly 155.96,
    matching the already-verified top-level Interest & Finance Charges
    claimed figure.

15. **Cross-document field matching must be scoped by source table, not
    just by label text — confirmed as a real bug, not just a
    precaution.** `arr_budget.py`'s `ARR_FIELD_MAP` was designed with
    title-scoping from the start (see finding #12), but
    `petition_claims.py`'s `match_schema_to_petition` matched purely on
    normalized label across every petition row found. This silently
    cross-matched TUO Table 2.9's "Sub total" (an unrelated per-project
    O&M rollup, part of a hydel/solar project cost breakdown that has
    nothing to do with interest charges) against Table G10's "Sub Total"
    (the interest-charges subtotal), attaching G10's claimed value
    (155.96 / 196.15) to a completely unrelated field — caught by
    noticing an unexplained extra row in test output, not by a crash or
    an error. Fixed by adding `tuo_title_pattern` to each `PETITION_TABLES`
    entry and filtering matches through it, mirroring `ARR_FIELD_MAP`'s
    existing scoping. **Any future addition to either mapping needs this
    scoping from the start — a bare label match across a whole document's
    worth of tables is not safe in these documents,** which reuse short
    generic labels ("Total", "Sub Total", "Balance") in many unrelated
    contexts.

16. **Chapter detection for all three SBUs needs two rules the SBU-G-only
    version got away without — fixed** (`list_chapters` /
    `find_sbu_chapter`). (a) Chapter numbers must increase: ARR page 176
    starts with the prose sentence "Chapter-3 of this order is extracted
    below" inside Chapter 5 (SBU-T), which otherwise reads as a new chapter
    and cuts SBU-T off at page 175, losing Table 5.17 onward. (b) A heading
    that names several SBUs is a shared chapter, not any one SBU's (the
    Truing Up Order's Chapter 6, "apportioning ... among SBU-G, SBU-T and
    SBU-D"). Each SBU is recognised by name OR code, since the petition's
    SBU-T heading is "SBU – T & SLDC" with no "Transmission". Verified: the
    right chapter for all 15 SBU/document combinations, SBU-G's page ranges
    unchanged. Chapter locations: TUO Ch.2/3/5 (G/T/D; energy sales and T&D
    loss sit in Ch.4, outside SBU-D's chapter), ARR Ch.4/5/6, petitions
    Ch.2/3/4.

17. **Text overflowing from one row's cell into the next row's gets woven
    into it character by character — fixed** (`fix_overflow_cells`). A
    wrapped label's last word, drawn past its row border, lands in the next
    row's cell at almost the same height as that row's own text, and
    pdfplumber's default line grouping interleaves the two: "Edamon - Kochi
    line compensation" came out as "TErduasmt on - Kochi..." ("Trust" woven
    in), "ARR" as "AAvRaRil ability". Two lines of genuine text in one cell
    never overlap vertically, so a cell with two vertically overlapping
    lines is the signal, and the upper line goes back to the row above.
    **A first version that also moved numbers was wrong in every numeric
    case** — confirmed by a cell-level diff of all five documents, which
    showed values shifted up a row (ARR Table 6.25's Non-tariff Income
    moved into its ARR row) and dropped header cells. Now restricted to
    letters-only label text, a non-empty remainder, not the first row, and
    same-size fonts (so a superscript "*" isn't mistaken for overflow).
    Re-diffed: every remaining change is a correct fix. **Not fixable this
    way:** two pieces of text on the same baseline that physically overlap
    in the PDF (a few SBU-D station names, e.g. "ENxLpCa nIIs ion" for "NLC
    II Expansion") — there's no height difference to separate them by.

18. **Page-break continuations are now merged in the core extraction even
    when the column count changes — fixed, replacing finding #13's
    per-table patch as the primary mechanism.** Finding #13 said a third
    occurrence should trigger a core fix; the 2024-25 petition's SBU-T
    summary (Table T6, 8 columns -> 5 across the page break) was that
    occurrence, and its SBU-D chapter had 225 fragments. When the first
    table on a page has no "Table" marker above it, sits in the same
    horizontal span as the table left open on the previous page, and starts
    with a data row, its cells are placed into the open table's columns by
    horizontal position (`remap_to_open_table`) — using the positions of
    columns that actually hold values on the first page (thin empty spacer
    columns would otherwise attract right-aligned figures), containment
    first, then nearest. Orphaned first rows (finding #11) use the same
    geometry. Supporting rules, each found from a wrong result: drop a
    table detected entirely inside another (G8's wrapped "ARR / Approval"
    header came back as its own tiny table and closed G8 early); a
    mismatched table that opens with a header row is a new table, not a
    continuation; a paragraph detected as a table row ("6.267 | The
    Non-Tariff income ...") is not data just because it starts with a
    clause number; a continuation's repeated header rows are dropped.
    Results: 2024-25 petition fragments G 48->24, T 18->1; 2024-25 TUO D
    30->3; 2023-24 TUO G 5->0, D 51->7 (recovering e.g. SBU-D summary Table
    5.1's last 13 rows and Table 5.9's 16 central-station rows); ARR D
    57->34. `recover_g8_tail` stays as a fallback but no longer fires for
    the known case. Stored documents are re-extracted automatically on
    server start when their `extraction_version` is older than the code's
    (reviewed tables are carried over).

## What already exists

Extraction (`backend/extraction/extract_sbu_g.py`): implements findings
#1–9 and #11 in full, and has real, partial progress on #10 (see above).
Tested Python using only `pdfplumber` (no AI/API calls). Outputs JSON:
`{"order_tables": [...], "reference_tables": [...],
"unclassified_fragments": [...], "chapter_heading": "...", "pages":
[start, end]}`, where each table has `table_no`, `title`, `pages`,
`header`, `unit_row`, `data_rows`, `needs_review`.

Schema discovery (`backend/extraction/schema_discovery.py`, new): stage
(i) of the pipeline. Given a Truing Up Order's `order_tables`, infers
which rows in each table are real data fields (a label plus at least one
numeric value) versus section headings with no figures of their own.
Deliberately NOT deduplicated across tables — the same concept (e.g.
"Depreciation") legitimately reappears in multiple summary tables within
one document (Table 2.2 vs 2.18 vs 2.19), and collapsing that here would
throw away real structure; cross-table/cross-document deduplication into
canonical concept keys belongs to the field-matching registry (step 2),
not this stage. Verified against the actual `Truing Up Order 23-24.pdf`
text (table 2.2's field labels match the source verbatim) and confirmed
to generalize cleanly to `TRUING UP ORDER 24-25.pdf` (same table
numbers, same field labels, year references updated) — 137 fields across
19 tables for 23-24, 139 fields across 16 tables for 24-25 after finding
#11's fix. Table 2.19 ("Approved Transfer Cost of SBU-G") turned out to
be the most complete single-table source for the canonical field list —
it includes "Additional contribution to Master Trust", which Table 2.2
is missing entirely in some years.

**Source PDFs located**: the five real documents (previously only
described in this brief) are at `Downloads/KSERC/`: `Truing Up Order
23-24.pdf`, `TRUING UP ORDER 24-25.pdf`, `ARR 2022-27.pdf`, `2023 -24
petition by ksebl.pdf`, `2024-25 petition by ksebl (1).pdf`. The 24-25
petition is new since this brief's last update — it pairs with the 23-24
Truing Up Order (schema source) and the ARR (approved budget) to test
the full stage (i)→(ii)→(iii) pipeline end-to-end once stage (iii)
exists.

ARR budget extraction (`backend/extraction/arr_budget.py`, new): stage
(ii) of the pipeline. For each stage-1 schema field covered by its
curated `ARR_FIELD_MAP`, pulls the Commission-APPROVED figure for a given
target year from the ARR's own control-period summary tables (4.60/4.63
for the top-level ARR components, 4.22/4.30/4.53 for their sub-breakdowns
where the ARR budgets them separately, 4.23 for the O&M
Employee/A&G/R&M split). Not a generic fuzzy matcher — every mapping was
hand-verified against real cross-document values before being added (see
finding #12 for a real bug this surfaced and fixed: matching must key on
table TITLE, not table NUMBER, since numbers drift between document
years). Verified end-to-end for both FY2023-24 and FY2024-25: of the 13
canonical top-level fields (Table 2.2/2.19's schema), 9 have a confirmed
ARR-approved figure that matches the Truing Up Order's own reprint of
that number EXACTLY (independently double-sourced), and 4 (Cost of
Generation of Power, Amortisation of intangible assets, Exceptional
Items, Others) are confirmed to have no separate ARR budget line at all —
the Truing Up Order's own approved-column value for those is 0.00/blank,
consistent with the ARR simply not budgeting them. The 3 O&M sub-items
(Employee Cost/A&G Expenses/R&M Expenses) are also extracted, sourced
from ARR Table 4.23's stated cost ratios (77.03%/4.32%/18.65%) applied to
the O&M total — internally consistent (sums back to the O&M total) but
only single-sourced, since the Truing Up Order itself never reprints that
particular breakdown to cross-check against (confirmed: Table 2.7's own
"approved" column is a single value merged across all three sub-item
rows in the source PDF, not a per-item breakdown — not an extraction
bug, that's genuinely how the source document prints it).

**Intended end-to-end workflow (as confirmed by the project owner):**
upload the PREVIOUS year's Truing Up Order (e.g. 2023-24) → learn the
schema from it (which fields a truing-up order needs) → upload the ARR
(5-year control-period ceilings) → upload the CURRENT year's petition
(e.g. 2024-25) → dashboard compares the petition's claimed ("TU
Sought") figures against ARR-approved → reviewer verifies → stage (iv)
generates the current year's Truing Up Order following the previous
order's structure. Documents are picked in the dashboard, never
hardcoded. The comparison basis is TU Sought (the claim KSERC rules on),
not the petition's raw "Actuals" column — confirmed by the owner.

**Input guard (`backend/doc_meta.py`, `comparison.check_inputs`):** each
upload is classified as Truing Up Order / ARR order / truing-up petition
from several independent signals (cover-page phrases, chapter heading,
table-numbering style) — deliberately not one exact phrase, since the
2023-24 petition's cover text is OCR-garbled — along with its financial
year (or the ARR's control period). A comparison is refused, with a
specific message, when a slot holds the wrong document type, the same
document is used twice, the year isn't YYYY-YY, the year is outside the
ARR's control period, or the petition's year doesn't match. A same-year
or later Truing Up Order is only a warning. The dashboard's dropdowns
offer only documents of the matching type and pre-fill the year from the
petition. Comparisons created before this existed are checked on first
open and labelled if mismatched. Added because real use had produced
comparisons with a petition in the ARR slot, a petition in the TUO slot,
and a TUO in the petition slot with the year typed as "23-24" — all
silently accepted. Also added: delete-comparison, cleanup of refused
uploads (they used to leave the PDF on disk), and 32-hex-char ID
validation on every ID-based path (an encoded backslash in a DELETE URL
could otherwise escape the comparisons folder on Windows).

**New-document readiness:** ARR tables are now located by title, not by
table number (the 2022-27 ARR's 4.22/4.23/4.30/4.53/4.60/4.63 will be
numbered differently in the next control period's ARR). An expected ARR
row that can't be found, or a missing year column, now shows as "Needs
review" rather than as a confirmed "no ARR line", and a comparison where
no claimed or no approved values are found at all carries a warning that
the document's layout may differ from the ones this was verified on.

**O&M component claims (Table G13) — confirmed absent in the source, not
an extraction gap:** the petition's "TU requirement" column is blank for
Employee Cost / A&G / R&M in both years (checked against raw PDF text);
KSEB claims O&M only as a normative total. These rows now show the
ARR-approved figure with an explicit "No separate claim" flag and a link
to the source page. While wiring this in, a case-insensitive column
pattern `TU` matched inside "Ac**tu**al" and read the Actuals column as
the claim (a +2452% "deviation" on A&G) — fixed with `\bTU\b`. Column
patterns need word boundaries when short.

**Coverage as of the field-mapping sweep** (both `ARR_FIELD_MAP` and
`PETITION_TABLES` extended together, findings #14–15 fixed along the
way): 26 fields now shown per comparison (ARR-approved + petition-claimed +
computed deviation, or an explicit "no ARR line" / "no separate claim"
flag), up from the original 18 — adding the Interest &
Finance Charges breakdown (Interest on Capital Liabilities, GPF, Working
capital, Master Trust Bonds, Sub Total, plus 3 confirmed "not budgeted"
items: Other Interests, Less: Capitalized, Balance), sourced from ARR
Table 4.53 and Petition Table G10 (same verification discipline as
everything else — every 2024-25 sub-item cross-checked against ARR 4.53's
approval column, and the five claimed sub-items sum to exactly the
already-verified top-level total).

**Deliberately still not covered**, after inspecting the remaining ARR
tables (4.19–4.21 RE/new-project O&M rates, 4.41–4.46 working-capital
mechanics) and classifying the schema's ~110 remaining fields:
- **Calculation methodology / rate tables** (RE project O&M norms in
  Rs. Lakh/MW, working-capital interest-rate derivation steps, base-rate
  lookups) — these aren't independent "claimed vs approved cost" figures
  the way the mapped fields are; they're formula inputs that already roll
  up into totals this pipeline captures (e.g. the working-capital
  interest calculation's *result* is part of Interest & Finance Charges).
  Force-mapping them into the same claimed-vs-approved comparison model
  would misrepresent what they are.
- **Physical quantities** (installed capacity MW, generation MU by
  month/station, fuel cost station-wise breakdowns) — not Rs. Cr cost
  figures; "Cost of Generation of Power" (which these feed into) is
  already confirmed to have no separate ARR budget line at all.
- **Per-project granular detail** (Table 2.9-style project-by-project O&M
  cost rows) — lower priority; the totals they roll up into are already
  covered by the O&M mapping.

**SBU-T and SBU-D — mapped and verified, all three SBUs comparable.**
Same discipline as SBU-G: every approved value checked against the
orders' own "MYT Order" column, every claim against the orders' reprint
of the petition, for both FY2023-24 and FY2024-25 (schema from TUO
2023-24 in both runs, per the owner's workflow). Maps:
`ARR_FIELD_MAP_T` / `ARR_FIELD_MAP_D` in `arr_budget.py`,
`PETITION_TABLES_T` / `PETITION_TABLES_D` plus per-SBU aliases and
"no separate claim" groups in `petition_claims.py`.
- **SBU-T** (23 fields): summary (ARR tables titled "KSERC approval-
  ARR of SBU-T" / "... Net ARR of SBU-T"), O&M components (no separate claim
  — O&M is claimed only as a normative total), interest breakdown. The
  petition's claimed column is "Truing up requirement"; in 2024-25 T6
  every value sits one column left under a blank header
  (`_shifted_index`, judged across the whole table, applied AFTER any
  whole-table offset or SBU-G's G10 gets corrected twice). Source
  discrepancies shown as-is, ARR is the authority: 2023-24 order reprints
  Repayment 45.81 vs ARR 45.79, ARR 1588.21 vs 1588.20.
- **SBU-D** (29 fields + new lines, below): summary from ARR Table 6.180
  "Summary of Approved ARR&ERC for the control period"; Employee & A&G
  from 6.119; R&M from 6.124, which lists YEARS DOWN THE ROWS
  (`year_rows` option → `find_year_rows_column`); interest breakdown from
  6.158's KSERC half. Petition: D76/D89 summary ("True up"), D75
  components (the 2023-24 petition's D63 has only the O&M total, so its
  components come back blank), D65/D77 "Comparison of I&FC" (not D71,
  which splits the carrying cost in two). Specifics that each needed code:
  - TUO 23-24 Table 5.1 has three labels garbled by same-baseline overlap
    (finding #17's limit); the same fields are taken from Table 5.90/5.94,
    which print them cleanly. The map is scoped to all three titles.
  - "Carrying cost on revenue gap till 2023-24" changes wording every
    year → `label_key()` drops a trailing year before matching (used by
    the ARR map and petition matching, NOT by ARR row lookup, where a
    year-only row label must survive).
  - The ARR states the revenue gap positive (2939.09), the petition as
    "(-)2939.12" → map option `negate`; `to_float` parses "(-)" and
    "(- )1,323.75"; deviation % divides by |approved| so a negative
    approval doesn't flip its sign.
  - "Sharing of gains ... T&D loss reduction" row: values one column
    left under a blank header, with NO cell (None, not "") where the
    named column is → `_row_shifted_index`, only for exactly that shape.
  - Petition has no Net ARR line → "no separate claim". Tariff income,
    power-factor incentive and Total ERC are deliberately not compared:
    the ARR budgets tariff revenue net of the PF incentive (15873.80 =
    15903.34 − 29.54), so neither line compares one-to-one.
  - Cross-SBU check holds: SBU-D's Cost of Generation claim = SBU-G's Net
    ARR claim (626.48 / 714.05); Intra-State Transmission = SBU-T's Net
    ARR claim (1553.14 / 1654.89).
- Fields are listed in map order (which follows the orders' summary
  tables), not schema order.

**New claim lines** (`new_petition_lines`): the schema is last year's
order, so a head of claim that's new this year was silently never
compared — the 2024-25 petition's SBU-D "Registration charges for solar
refunded" (24.18) and "Refund of liquidated damages" (16.30), and SBU-T
"Refunded liquidated damages" (0.13). Each SBU's summary petition table
(`report_new_lines`) is now checked for lines with a value that last
year's summary table lacks (aliases respected); they're added as
stand-in schema fields and shown flagged "New line" (plus "Needs review"
if no ARR line is mapped). A line whose claimed amount is already matched
to another field is not new — SBU-T's petition summary repeats the
interest breakdown under different names ("Interest on loan" 409.93 =
"Interest on Outstanding Capital" 409.93).

**Known gap for a 2025-26 run** (TUO 24-25 as template): its SBU-D
Tables 5.1/5.85/5.90 lose the "Sharing of gains ..." row label entirely
(the row comes back `[None, '0.00', '131.85', ...]`), so that line would
arrive via the new-line check rather than the schema. Unverified until a
2025-26 petition is available.

Extend `ARR_FIELD_MAP`/`PETITION_TABLES` incrementally, one verified
concept at a time, rather than trying to cover everything at once — and
scope every new entry by source table from the start (finding #15), not
just by label text.

Petition claims (`backend/extraction/petition_claims.py`, new): stage
(iii) of the pipeline, the claimed-values half. Unlike stage (ii), no
alias table was needed — the Petition's own Table G8 ("ARR OF GENERATION
BUSINESS UNIT (SBU-G) for `<year>`") uses the EXACT same field labels and
row order as the Truing Up Order's Table 2.2/2.19, confirmed across both
petition years. Pulls the "TU Sought" column (what KSEB is asking to be
trued up to — the actual claim) per field; also carries G8's own "ARR
Approval" and "Actuals" columns for cross-reference, though the
authoritative ARR-approved figure for the dashboard comes from stage
(ii)'s `arr_budget.py`, not from this reprint. Does NOT extract G8's own
"Difference" column — its header text sits one column away from where
its value actually lands (a table-wide offset, confirmed across every
row), and the pipeline computes deviation itself downstream anyway (see
`compare.py`), so a second undertested repair for an unneeded value
wasn't worth adding. Required its own repair for a per-row shift on the
"Net ARR" row specifically (`_realign_row` — a real value landing under a
None/padding header column, one cell removed to restore alignment) and
`recover_g8_tail` for the page-break bug (finding #13). Verified for both
FY2023-24 (15/15 canonical fields, all values match the source PDF and
cross-check against the Truing Up Order's own reprint) and FY2024-25
(same, after finding #13's fix).

Comparison (`backend/extraction/compare.py`, new): joins stage (ii)'s
ARR-approved figure and stage (iii)'s petition-claimed figure per field,
computing deviation (absolute and %) itself rather than trusting either
document's own printed "difference" — confirmed this was the right call,
not just a caution: the Truing Up Order's own printed difference for the
O&M "existing stations" sub-row is a merged-cell artifact belonging to
the O&M total, not that sub-row (its true per-row deviation, 5.28, only
shows up when computed directly from claimed − approved). Verified
end-to-end for both FY2023-24 and FY2024-25: 13 canonical top-level
fields fully compared, computed deviations matching the source
documents' own printed figures exactly wherever a document prints an
unambiguous one to check against (e.g. FY2024-25's ARR deviation:
computed 7.69, source prints 7.69).

**What stage (iii) does NOT yet do**: the reviewer-configurable
deviation-threshold settings (percentage + absolute floor, see
"Deviation thresholds" below), the dashboard UI itself, and the XAI
explanation layer are all still unbuilt — this stage only produces the
comparison data a dashboard would consume. `compare.py`'s output
(`comparison_output.json`) is shaped for that: one row per field with
`arr_approved`, `petition_claimed`, `deviation_abs`, `deviation_pct`.

Backend (`backend/main.py`, `backend/storage.py`) — FastAPI app:
- `POST /api/documents/upload` — accepts a PDF, runs extraction, stores
  result + source PDF under a generated `doc_id`.
- `GET /api/documents` — list uploaded documents with summary counts.
- `GET /api/documents/{doc_id}` — full extracted data for one document.
- `PATCH /api/documents/{doc_id}/{bucket}/{index}` — edit a table's
  `data_rows` and/or toggle its `reviewed` flag.
- `GET /api/documents/{doc_id}/page/{page_number}.png` — renders a PDF
  page to PNG via PyMuPDF, for the "view source page" requirement.
- Serves `frontend/` as static files at `/`.

Frontend (`frontend/index.html`, `app.js`, `styles.css`, 501 lines
total): document list + single-document table review view. Verify
current capabilities directly against `app.js` before building on top of
assumptions here — this brief doesn't re-derive its exact feature set.

**Treat the extraction script as a strong, proven foundation to keep
improving — not a finished black box, and not something to throw away
and rewrite.** Every fix in findings #1–10 was found by: printing raw
pdfplumber output for a specific table/page, cross-referencing against
the actual PDF text side by side, finding the real cause, fixing, then
re-running the FULL script against all documents to confirm nothing
regressed before moving on. Continue that discipline.

**Immediate next task on the extraction side**: finish finding #10's
investigation — verify the current `unclassified_fragments` output
(especially the Petition's 33) against the actual PDF text the same way
every prior fix was verified, not assumed correct because the mechanism
exists.

## Field-matching design (needed for stage iii — not yet built)

Since the same financial concept ("Cost of Generation of Power," "O&M
Expenses," etc.) is labeled differently in all three document types (see
finding #1), a canonical field registry is needed to match rows across
documents:

1. **Canonical field registry**: a fixed set of concept keys for SBU-G
   (e.g. `cost_of_generation_of_power`, `om_expenses_existing_stations`,
   `om_expenses_new_stations`, `om_expenses_total`,
   `interest_finance_charges`, `depreciation`,
   `repayment_master_trust_bond`, `additional_contribution_master_trust`,
   `amortisation_intangible_assets`, `roe`, `exceptional_items`,
   `other_charges`, `gross_arr`, `non_tariff_income`, `net_arr`). Each key
   stores an expected unit (Rs. Cr, MU, %, etc.) and a growing list of
   alias strings seen across documents so far.
2. **Matching pipeline** for each extracted row label: (a) exact alias
   match (normalized: lowercase, strip punctuation, collapse whitespace)
   → auto-accept; (b) fuzzy match against the alias list using
   token-based similarity (rapidfuzz `token_sort_ratio`/`token_set_ratio`
   — NOT plain edit-distance, since word order differs a lot between
   documents, e.g. "O&M expenses of SBU-G claimed by KSEB Ltd" vs. "O&M
   cost of SBU-G claimed and approved"); (c) unit must match the
   registry's expected unit — a high text-similarity match with a
   mismatched unit is disqualified outright, never overridden by text
   similarity alone; (d) section-scoped — only compare against candidate
   keys from the same table/category context, to cut false positives
   from generically-worded rows like "Total."
3. Rows clearing the above above a confidence threshold auto-populate on
   the dashboard; rows below it are shown unmapped with a dropdown for
   the reviewer to assign to an existing key or create a new one.
4. **The registry learns from reviewer corrections**, not retraining —
   every confirmed/corrected mapping appends that row label to the
   canonical key's alias list, so next year's document is more likely to
   hit an exact alias match. This keeps the system fully explainable
   (a growing dictionary, not a trained model) and needs no training data.
5. **Numeric plausibility** (same order-of-magnitude check between
   matched ARR/Petition/Truing-Up figures) is a secondary sanity flag
   only ("claimed is 50× approved — check this mapping"), never used to
   decide whether a match is correct, since large deviations are
   literally what the system exists to surface.

`rapidfuzz` is not yet in `backend/requirements.txt` — add it when this
layer gets built.

## Deviation thresholds — reviewer-configurable

Two knobs, not one, since fields differ wildly in scale (power purchase
cost is hundreds of crores; some O&M sub-items are single-digit crores):
- **Percentage threshold** (e.g. flag anything >X% off from ARR-approved).
- **Absolute floor** (e.g. only flag if the absolute difference also
  exceeds ₹Y Cr) — stops a tiny field with a wild % swing on a near-zero
  base from cluttering the dashboard with noise.

Both must be editable from the dashboard itself (a settings panel), not
hardcoded. Default to sensible starting values, tune once real deviations
from actual data are visible. **Not yet built** — the current frontend
has no settings panel or deviation computation.

## XAI layer (for later, not this phase, but the design intent)

For flagged deviations, especially in power purchase cost, show an
explanation of likely causes — weather/rainfall patterns, hydro-reservoir
levels, demand growth, fuel price changes. Earlier design discussion
concluded: gradient-boosted trees (XGBoost/LightGBM) for forecasting,
paired with SHAP for per-prediction explanations (waterfall chart showing
how much each input feature pushed a prediction up/down), given the small
dataset size (8–15 years of regulatory data) rules out deep learning.
Quantile regression recommended for uncertainty bands rather than bare
point forecasts. This is explicitly NOT in scope for the current phase —
noted here so the eventual design doesn't contradict earlier decisions.

## What to build this phase (concrete, in order)

1. **Finish verifying the Petition's (and now ARR's/TUOs') unclassified
   fragments** against source PDF text — see finding #10's current
   status above. Do this before trusting the extraction layer as "done."
2. **Build the canonical field registry** for SBU-G (the field-matching
   design above), seeded from the actual table/row labels already
   extracted from all documents (see `backend/extraction/sbu_g_extract.json`
   and the per-document `data.json` files under `backend/uploads/`).
3. ~~Backend (FastAPI): endpoint(s) to run the extraction script against
   an uploaded PDF and return its JSON output.~~ **Done** — see
   `backend/main.py`. Keep following its existing rule: don't silently
   "clean up" or reinterpret `data_rows` in the API layer — if something
   needs fixing, fix it in the extraction logic itself so it's provable
   against the source PDF.
4. **Matching layer**: wire extracted rows from all three documents
   through the field registry, resolving to canonical keys with a
   confidence indicator per row. Not started.
5. **Dashboard**: show ARR-approved vs. Petition-claimed per canonical
   field, computed deviation, and a "Needs manual review" flag for (a)
   any table the extraction script itself flagged (`needs_review: true`)
   and (b) any row that failed to auto-match to a canonical field.
   Include the configurable percentage/absolute deviation-threshold
   settings panel. Include a "view source page" button rendering the
   actual PDF page image — **the page-image endpoint already exists**
   (`GET /api/documents/{doc_id}/page/{page_number}.png`), wire the
   frontend button to it. Reviewer can edit any cell inline (**already
   supported** via the PATCH endpoint), correct a field mapping (which
   appends to that canonical key's alias list — needs the registry from
   step 2 first), and mark items "Reviewed" (**already supported**).
6. **XAI/explanation layer and Truing Up Order generation (stage iv) are
   explicitly OUT of scope for this phase** — don't build them yet, but
   don't design anything in steps 1–5 in a way that would need to be
   reworked when they're added later (e.g. keep the canonical field
   registry and deviation data in a form an explanation layer could
   later attach to).

## Constraints and preferences

- No AI/LLM API costs anywhere in the running pipeline - local,
  open-source only.
- Prefer concise, direct explanations of what changed and why, not long
  narration of every step.
- Confirm you've understood the document-format quirks above (findings
  #1–10) before writing extraction code — they are not edge cases, they
  are the normal, recurring behavior of these documents and will very
  likely resurface on any new PDF this system ingests (a future year's
  Truing Up Order, a different KSEB filing, etc.).
- Scope discipline matters here: this project's biggest wasted effort so
  far came from building broadly (all chapters, all SBUs, dashboard UI)
  before the extraction layer was verified. Keep narrowing to SBU-G, keep
  verifying against real source PDFs before moving to the next layer —
  including the extraction layer's own newest addition (finding #10's
  `unclassified_fragments`), which has not yet had that verification
  pass despite the mechanism being built.
