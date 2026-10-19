import pytest

from extraction.extract_sbu_g import _looks_like_marker, match_marker


@pytest.mark.parametrize("line, table_no, is_order, title", [
    ("Table 2.1 Summary of the KSEBL own generation", "2.1", True, "Summary of the KSEBL own generation"),
    ("Table- G 1", "G1", True, ""),
    ("Table-T 2: ARR of SBU-T", "T2", True, "ARR of SBU-T"),
    ("Table – G2: Details", "G2", True, "Details"),
    ("Table :4.61 Approved", "4.61", True, "Approved"),
    ("Table V(3)", "V3", False, ""),
    # lettered parts must stay distinct tables (2023-24 petition, p.69)
    ("Table D 23(a) Ash transportation expenses", "D23(a)", True, "Ash transportation expenses"),
    ("Table D23 (b)Supplementary claims (Rs Cr)", "D23(b)", True, "Supplementary claims (Rs Cr)"),
    ("Table 6.33 (a) Year wise details", "6.33(a)", True, "Year wise details"),
    # a title that merely starts with a bracket is not a part letter
    ("Table 5.1 (Rs. Cr) claim", "5.1", True, "(Rs. Cr) claim"),
])
def test_table_markers(line, table_no, is_order, title):
    mm = match_marker(line)
    assert mm
    assert _looks_like_marker(mm.group(1).upper(), mm.group(2)) == (table_no, is_order)
    assert mm.group(3).strip() == title
