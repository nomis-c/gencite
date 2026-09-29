"""Step 2: gene symbol -> Ensembl ID, Entrez ID and gene type via MyGene.info.

An unknown symbol is not an error: it comes back with found=False, and the later steps
skip retrieval and the LLM for it (evidence level "none").
"""

import time

import requests

MYGENE_URL = "https://mygene.info/v3/query"

MYGENE_TIMEOUT = 10
MYGENE_MAX_RETRIES = 2
MYGENE_RETRY_BACKOFF = 0.5


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


def _get_with_retries(
    url: str,
    params: dict,
    timeout: int = MYGENE_TIMEOUT,
) -> requests.Response:
    """
    Perform a GET request with a small number of retries for
    transient network failures.

    Retry:
    - timeouts
    - connection errors
    - HTTP 429
    - HTTP 5xx

    Do not retry ordinary client errors such as 400 or 404.
    """

    for attempt in range(MYGENE_MAX_RETRIES + 1):
        try:
            response = requests.get(
                url,
                params=params,
                timeout=timeout,
            )
            response.raise_for_status()
            return response

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ):
            if attempt == MYGENE_MAX_RETRIES:
                raise

        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None

            retryable = status_code == 429 or (
                status_code is not None and 500 <= status_code < 600
            )

            if not retryable or attempt == MYGENE_MAX_RETRIES:
                raise

        time.sleep(MYGENE_RETRY_BACKOFF * (attempt + 1))

    raise RuntimeError("MyGene request failed after retries.")


def resolve_gene_id(symbol: str) -> dict:
    """
    Resolve a human gene symbol using MyGene.info.

    Returns a dictionary containing the gene symbol,
    official gene name, Ensembl ID, Entrez ID, gene type,
    and whether the gene could be resolved.
    """

    params = {
        "q": f"symbol:{symbol}",
        "species": "human",
        "fields": ("symbol,name,ensembl.gene," "entrezgene,type_of_gene"),
        "size": 5,
    }

    response = _get_with_retries(
        MYGENE_URL,
        params=params,
    )

    data = response.json()

    for hit in data.get("hits", []):
        # Make sure we actually got the requested human gene symbol.
        if hit.get("symbol", "").upper() == symbol.upper():
            return {
                "symbol": hit.get("symbol", symbol),
                "name": hit.get("name"),
                "ensembl_id": _extract_ensembl_id(hit.get("ensembl")),
                "entrez_id": (
                    str(hit["entrezgene"]) if hit.get("entrezgene") else None
                ),
                "gene_type": hit.get("type_of_gene"),
                "found": True,
            }

    return {
        "symbol": symbol,
        "name": None,
        "ensembl_id": None,
        "entrez_id": None,
        "gene_type": None,
        "found": False,
    }


def resolve_gene_ids(
    symbols: list[str],
) -> list[dict]:
    """Resolve a list of human gene symbols."""
    return [resolve_gene_id(symbol) for symbol in symbols]
