import requests
import xml.etree.ElementTree as ET


ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def search_pubmed(gene_symbol: str, max_results: int = 5) -> list[str]:
    params = {
        "db": "pubmed",
        "term": f"{gene_symbol}[Title/Abstract]",
        "retmode": "json",
        "retmax": max_results,
        "sort": "relevance",
    }

    response = requests.get(ESEARCH_URL, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()
    return data.get("esearchresult", {}).get("idlist", [])


def fetch_pubmed_records(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }

    response = requests.get(EFETCH_URL, params=params, timeout=10)
    response.raise_for_status()

    root = ET.fromstring(response.text)

    records = []

    for article in root.findall(".//PubmedArticle"):
        pmid = article.findtext(".//PMID")

        title_elem = article.find(".//ArticleTitle")
        title = "".join(title_elem.itertext()) if title_elem is not None else ""

        abstract_parts = []
        for abstract_text in article.findall(".//AbstractText"):
            abstract_parts.append("".join(abstract_text.itertext()))

        abstract = " ".join(abstract_parts)

        records.append({
            "id": f"PMID:{pmid}",
            "source": "pubmed",
            "title": title,
            "text": abstract,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })

    return records


def retrieve_pubmed_evidence(gene_symbol: str, max_results: int = 5) -> list[dict]:
    pmids = search_pubmed(gene_symbol, max_results=max_results)
    return fetch_pubmed_records(pmids)