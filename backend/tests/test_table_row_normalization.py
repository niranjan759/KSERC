from extraction.extract_sbu_g import normalize_table_rows


def test_normalize_table_rows_pads_and_trims_to_header_width():
    header = ["SI No", "Hydro Station", "2022-23", "2023-24"]
    rows = [
        ["1", "Idukki", "2478.65"],
        ["2", "Sabarigiri", "1397.74", "1543.28", "1551.15"],
    ]

    normalized = normalize_table_rows(header, rows)

    assert normalized == [
        ["1", "Idukki", "2478.65", None],
        ["2", "Sabarigiri", "1397.74", "1543.28"],
    ]
