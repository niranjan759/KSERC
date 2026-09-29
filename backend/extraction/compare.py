"""Stage (iii)'s comparison step: join the ARR-approved figure (stage ii)
against the petition-claimed figure (stage iii) for each schema field, and
compute the deviation. The system computes this itself rather than trusting
either document's own printed "difference" column - see petition_claims.py
for why that column isn't reliable to extract directly."""

import re


def to_float(v):
    """Numbers as the documents print them: "12,982.59", and negatives
    written "(-)2939.12" or, when a cell wraps, "(- )1,323.75"."""
    if v is None or v == "":
        return None
    s = re.sub(r'\s+', '', str(v)).replace(",", "").replace("(-)", "-")
    try:
        return float(s)
    except ValueError:
        return None


def build_comparison(arr_budget_fields, petition_claim_fields):
    """arr_budget_fields: extract_arr_budget()'s output (stage ii).
    petition_claim_fields: match_schema_to_petition()'s output (stage iii).
    Joined on field_label. The ARR field map is the list of compared
    fields: every field in it appears (a missing petition claim shows as
    blank - a signal for the reviewer), including fields the ARR confirms it
    doesn't budget. A petition row with no entry in that map is not a
    compared field - e.g. SBU-T's interest breakdown "Total", which just
    repeats "Interest & Finance Charge" - and is left out rather than shown
    as a claim with nothing to compare it against."""
    approved_by_label = {f["field_label"]: f for f in arr_budget_fields}
    claimed_by_label = {f["field_label"]: f for f in petition_claim_fields}

    # plus claim lines new in this petition (petition_claims.new_petition_lines)
    # that the ARR map doesn't cover: a claim nobody has checked yet must be
    # shown, not dropped
    all_labels = list(dict.fromkeys(
        [f["field_label"] for f in arr_budget_fields]
        + [f["field_label"] for f in petition_claim_fields if f.get("new_in_petition")]))

    rows = []
    for label in all_labels:
        a = approved_by_label.get(label)
        c = claimed_by_label.get(label)

        approved_raw = a["approved_value"] if a else None
        claimed_raw = c["claimed_value"] if c else None
        approved = to_float(approved_raw)
        claimed = to_float(claimed_raw)

        deviation_abs = None
        deviation_pct = None
        if approved is not None and claimed is not None:
            deviation_abs = round(claimed - approved, 2)
            if approved != 0:
                # against the size of the approval: SBU-D's revenue gap is
                # negative, and dividing by it would flip the percentage's sign
                deviation_pct = round(deviation_abs / abs(approved) * 100, 2)

        needs_review = bool((a or {}).get("needs_review")) or bool((c or {}).get("needs_review"))
        new_line = bool((a or c).get("new_in_petition"))
        lookup_problem = (a or {}).get("lookup_problem")
        if new_line and a is None:
            needs_review = True
            lookup_problem = ("New claim line - not in last year's Truing Up Order, and no ARR line "
                              "is mapped for it; enter the approved figure if the ARR has one")
        rows.append({
            "field_label": label,
            "schema_table_no": (a or c)["schema_table_no"],
            "unit": (a or c).get("unit"),
            "arr_approved": approved_raw,
            "petition_claimed": claimed_raw,
            "deviation_abs": deviation_abs,
            "deviation_pct": deviation_pct,
            "note": (a or {}).get("note"),
            "claim_note": (c or {}).get("claim_note"),
            "lookup_problem": lookup_problem,
            "new_in_petition": new_line,
            "needs_review": needs_review,
            "arr_pages": (a or {}).get("pages", []),
            "petition_pages": (c or {}).get("pages", []),
            "reviewed": False,
        })
    return rows


if __name__ == "__main__":
    import json
    import sys

    from extract_sbu_g import extract_section
    from schema_discovery import discover_schema
    from arr_budget import extract_arr_budget
    from petition_claims import match_schema_to_petition

    if len(sys.argv) < 5:
        print("Usage: python compare.py <truing-up-order.pdf> <arr.pdf> <petition.pdf> <target-year e.g. 2023-24> [G|T|D]")
        sys.exit(1)

    tuo_path, arr_path, petition_path, target_year = sys.argv[1:5]
    sbu = sys.argv[5] if len(sys.argv) > 5 else "G"

    tuo_result = extract_section(tuo_path, sbu)
    if "error" in tuo_result:
        print("Truing Up Order:", tuo_result["error"]); sys.exit(1)
    schema_fields = discover_schema(tuo_result["order_tables"])

    arr_result = extract_section(arr_path, sbu)
    if "error" in arr_result:
        print("ARR:", arr_result["error"]); sys.exit(1)
    arr_budget = extract_arr_budget(schema_fields, arr_result["order_tables"], target_year, sbu)

    petition_result = extract_section(petition_path, sbu)
    if "error" in petition_result:
        print("Petition:", petition_result["error"]); sys.exit(1)
    petition_claims = match_schema_to_petition(schema_fields, petition_result["order_tables"], petition_path, sbu)

    comparison = build_comparison(arr_budget, petition_claims)

    print(f"{'Field':<45} {'ARR Approved':>13} {'Petition Claimed':>17} {'Deviation':>12} {'%':>8}")
    for r in comparison:
        approved = r["arr_approved"] if r["arr_approved"] not in (None, "") else "-"
        claimed = r["petition_claimed"] if r["petition_claimed"] not in (None, "") else "-"
        dev = r["deviation_abs"] if r["deviation_abs"] is not None else "-"
        pct = f"{r['deviation_pct']}%" if r["deviation_pct"] is not None else "-"
        if r["note"]:
            flag = "  <-- no ARR budget line"
        elif r["claim_note"]:
            flag = "  <-- no separate petition claim"
        elif r["needs_review"]:
            flag = "  <-- needs review"
        else:
            flag = ""
        print(f"{r['field_label']:<45} {str(approved):>13} {str(claimed):>17} {str(dev):>12} {pct:>8}{flag}")

    with open("comparison_output.json", "w", encoding="utf-8") as fh:
        json.dump({"target_year": target_year, "fields": comparison}, fh, indent=2)
    print("\nWrote comparison_output.json")
