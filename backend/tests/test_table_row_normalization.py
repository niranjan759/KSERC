from extraction.extract_sbu_g import normalize_table_rows


def test_normalize_table_rows_pads_short_rows_and_trims_empty_overflow():
    header = ["SI No", "Hydro Station", "2022-23", "2023-24"]
    rows = [
        ["1", "Idukki", "2478.65"],
        ["2", "Sabarigiri", "1397.74", "1543.28", None, ""],
    ]

    normalized = normalize_table_rows(header, rows)

    assert normalized == [
        ["1", "Idukki", "2478.65", None],
        ["2", "Sabarigiri", "1397.74", "1543.28"],
    ]


def test_normalize_table_rows_never_drops_a_value():
    # a row wider than its header carries real figures (2023-24 petition
    # Table D23(b): Deviation charges / IT / FERV / Others / Total)
    header = ["Sl No", "Station", "RLDC"]
    rows = [["3", "Talcher", "-1.45", "11.32", "55.00", None]]

    assert normalize_table_rows(header, rows) == [["3", "Talcher", "-1.45", "11.32", "55.00"]]
