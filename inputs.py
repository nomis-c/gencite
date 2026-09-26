def parse_gene_list(text: str) -> list[str]:
    genes = []

    for line in text.splitlines():
        gene = line.strip()

        if not gene:
            continue

        if gene not in genes:
            genes.append(gene)

    return genes