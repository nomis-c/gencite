"""Step 1: gene list text -> clean list of symbols (header, comments, blanks and duplicates removed)."""

# Column names a first line can have. No human gene symbol is one of these, so a real first gene is never dropped.
HEADER_WORDS = {
    "gene",
    "genes",
    "symbol",
    "symbols",
    "gene_symbol",
    "gene_symbols",
    "genesymbol",
    "gene_name",
    "genename",
    "gene_id",
    "hgnc_symbol",
    "hgnc",
    "name",
    "id",
}


def is_header(line: str) -> bool:
    return line.strip().lower().replace(" ", "_").replace("-", "_") in HEADER_WORDS


def parse_gene_list(text: str) -> list[str]:
    genes = []
    first = True

    for line in text.lstrip("﻿").splitlines():  # ﻿: byte order mark from Excel exports
        gene = line.strip()

        if not gene or gene.startswith("#"):
            continue

        if first:
            first = False
            if is_header(gene):  # only the first real line can be a header
                continue

        if gene not in genes:
            genes.append(gene)

    return genes
