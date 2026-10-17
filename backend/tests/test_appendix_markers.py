from extraction.extract_sbu_g import is_prose_row, match_marker


def marker(text):
    m = match_marker(text)
    return (m.group(1), m.group(2)) if m else None


def test_appendix_titles_are_markers_in_every_form_seen():
    assert marker("Appendix 1 : Details of capital liabilities ( 2024-25)") == ("APP", "1")
    assert marker("Appendix 1A : Details of capital liabilities (2024-25)-SBU G") == ("APP", "1A")
    assert marker("Appendix 4 B : SBU G - Details of part capitalisation") == ("APP", "4B")
    assert marker("Appendix-2 : Details of the short-term loans") == ("APP", "2")
    assert marker("Appendix 4G: SBU T- PROJECT CODE WISE ASSET ADDITION") == ("APP", "4G")
    assert marker("(Contd) Appendix 3- Details of short-term loan Interest") == ("APP", "3")


def test_sentences_that_merely_mention_an_appendix_are_not_markers():
    assert marker("Appendix 1 gives the details of loans") is None
    assert marker("Appendix 4 Details of loans") is None
    assert marker("Appendix to Chapter-1") is None


def test_table_markers_still_match_as_before():
    assert marker("Table 2.1 Summary") == ("", "2.1")
    assert marker("Table- G 1 Hydel") == ("G", "1")


def test_a_project_code_heading_is_not_mistaken_for_a_numbered_paragraph():
    assert not is_prose_row(["", "14.01 - TRANSMISSION SCHEMES"])
    assert is_prose_row(["", "2.3.1 From the table, it may kindly be seen that the inflow"])
