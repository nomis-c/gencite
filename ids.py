import requests


MYGENE_URL = "https://mygene.info/v3/query"


def _extract_ensembl_id(ensembl_data):
    """Extract one Ensembl gene ID from MyGene.info response."""
    if not ensembl_data:
        return None

    if isinstance(ensembl_data, dict):
        return ensembl_data.get("gene")

    if isinstance(ensembl_data, list):
        for entry in ensembl_data:
            if isinstance(entry, dict) and entry.get("gene"):
                return entry["gene"]

    return None


def resolve_gene_id(symbol: str) -> dict:
    """
    Resolve a human gene symbol using MyGene.info.

    Returns a dictionary containing the gene symbol,
    Ensembl ID, Entrez ID, gene type, and whether
    the gene could be resolved.
    """

    params = {
        "q": f"symbol:{symbol}",
        "species": "human",
        "fields": "symbol,ensembl.gene,entrezgene,type_of_gene",
        "size": 5,
    }

    response = requests.get(MYGENE_URL, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()

    for hit in data.get("hits", []):
        # Make sure we actually got the requested symbol
        if hit.get("symbol", "").upper() == symbol.upper():
            return {
                "symbol": hit.get("symbol", symbol),
                "ensembl_id": _extract_ensembl_id(hit.get("ensembl")),
                "entrez_id": str(hit["entrezgene"]) if hit.get("entrezgene") else None,
                "gene_type": hit.get("type_of_gene"),
                "found": True,
            }

    return {
        "symbol": symbol,
        "ensembl_id": None,
        "entrez_id": None,
        "gene_type": None,
        "found": False,
    }


def resolve_gene_ids(symbols: list[str]) -> list[dict]:
    """Resolve a list of gene symbols."""
    return [resolve_gene_id(symbol) for symbol in symbols]