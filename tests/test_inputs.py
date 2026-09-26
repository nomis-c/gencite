from gencite.inputs import parse_gene_list


def test_header_comments_blanks_and_duplicates_are_removed():
    text = "Gene\n# a comment\n\nIRGM\n  SPG7  \nIRGM\nLCT\n"
    assert parse_gene_list(text) == ["IRGM", "SPG7", "LCT"]


def test_header_only_on_first_line():
    assert parse_gene_list("IRGM\nSymbol\n") == ["IRGM", "Symbol"]


def test_byte_order_mark_from_excel_is_ignored():
    assert parse_gene_list("﻿Gene\nIRGM\n") == ["IRGM"]


def test_empty_file():
    assert parse_gene_list("") == []
