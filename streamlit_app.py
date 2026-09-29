"""Web interface: upload a gene list, choose evidence sources, read and download the cited report."""

import html
import os
import re
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import streamlit as st

from gencite.collect_evidence import collect_evidence
from gencite.create_report import build_report
from gencite.ids import resolve_gene_id
from gencite.inputs import parse_gene_list
from gencite.schema import GeneRecord
from gencite.synth_LLM import synthesize
from gencite.verify import JUDGE_FAILED, verify

st.set_page_config(page_title="gencite", page_icon="🧬", layout="wide")


# ---------------------------------------------------------
# Wording
# ---------------------------------------------------------

# source key -> (name, what it contributes)
SOURCES = {
    "pubmed": (
        "NCBI PubMed",
        "Papers NCBI links to the gene; if there are none, a filtered text search.",
    ),
    "open_targets": ("Open Targets", "Gene biotype and disease associations."),
    "human_protein_atlas": (
        "Human Protein Atlas",
        "Tissue and cell-type expression, protein annotation.",
    ),
    "amass": (
        "AMASS",
        "Gene and protein summaries plus related papers. Needs AMASS_API_KEY.",
    ),
}

# verdict -> (label, what it means for the reader)
VERDICTS = {
    "supported": ("Supported", "The cited source says this."),
    "partial": ("Partly supported", "The core is in the source, the claim says more."),
    "unsupported": ("Not supported", "The cited source does not say this."),
    "invalid_id": (
        "Citation not found",
        "Cites a source that was not retrieved for this gene.",
    ),
    "unchecked": ("Not checked", "The verifier did not run for this claim."),
}


# ---------------------------------------------------------
# Styling: H&E stain palette, italic gene symbols as in papers
# ---------------------------------------------------------

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Literata:ital,opsz,wght@0,7..72,400;0,7..72,600;1,7..72,400;1,7..72,600&display=swap');
:root {
  --bg: #10172E; --panel: rgba(16, 22, 44, .72); --panel-solid: #161D38; --ink: #E4EAF3; --muted: #93A3BA; --rule: #2A3A53;
  --dapi: #8FA2FF;
  --v-supported: #4FC98A; --v-partial: #E9B949; --v-unsupported: #F2677A;
  --v-invalid_id: #D36AD6; --v-unchecked: #7D8CA3;
  --serif: 'Literata', Georgia, serif;
  --sans: 'Instrument Sans', system-ui, sans-serif;
}
.stApp, [data-testid="stAppViewContainer"] {
  background: linear-gradient(140deg, #0C1838 0%, #121B3F 30%, #2A1733 65%, #3F1022 100%) fixed; color: var(--ink); }
[data-testid="stHeader"] { background: transparent; }
.stApp, .stApp p, .stApp label, .stApp li, .stApp input, .stApp button, .stApp textarea,
.stApp [data-testid="stMarkdownContainer"], .stApp [data-testid="stCaptionContainer"] { font-family: var(--sans); }
.block-container { max-width: 1120px; padding-top: 3rem; padding-bottom: 5rem; }
.stApp a { color: var(--dapi); text-underline-offset: 2px; }
.stApp a:hover { color: #C3CDFF; }
.stApp a:focus-visible, .stApp button:focus-visible { outline: 2px solid var(--dapi); outline-offset: 2px; }
[class*="st-key-panel"] { background: var(--panel); backdrop-filter: blur(6px); border-color: rgba(143, 162, 255, .18) !important; border-radius: 10px; }

.gc-word { font-family: var(--serif); font-style: italic; font-weight: 600; font-size: 4rem;
  line-height: 1.05; letter-spacing: -0.015em; margin: .2rem 0 .9rem; padding-bottom: .1em;
  background: linear-gradient(90deg, #8FA2FF 0%, #C58BE0 55%, #EC7A92 100%); -webkit-background-clip: text; background-clip: text; color: transparent; }
.stApp .gc-lede { font-family: var(--serif); font-size: 1.45rem; line-height: 1.4; max-width: 30rem; margin: 0 0 .8rem; }
.stApp .gc-fine { color: var(--muted); font-size: .98rem; line-height: 1.55; max-width: 32rem; margin: 0; }
.gc-h { font-family: var(--serif); font-weight: 600; font-size: 1.2rem; margin: 0 0 .5rem; display: flex; gap: .6rem; align-items: baseline; }
.gc-step { font-family: var(--sans); font-weight: 600; font-size: .95rem; color: var(--dapi); }
.gc-read-h { font-family: var(--serif); font-weight: 600; font-size: 1.05rem; margin: 0 0 .7rem; }
.stApp .gc-read p { color: var(--muted); font-size: .9rem; line-height: 1.5; margin: .7rem 0 0; }

.stApp .gc-summary { font-family: var(--serif); font-size: 1.45rem; line-height: 1.45; max-width: 46rem; margin: 2.6rem 0 1.1rem; }
.gc-legend { display: flex; flex-wrap: wrap; gap: .4rem 1.3rem; color: var(--muted); font-size: .86rem; margin-bottom: .7rem; }
.gc-legend span { display: inline-flex; align-items: center; gap: .45rem; }
.gc-read .gc-legend { flex-direction: column; gap: .45rem; margin: .9rem 0 0; }

.gc-tracks { background: var(--panel); backdrop-filter: blur(6px); border: 1px solid var(--rule); border-radius: 10px; padding: .3rem 1.1rem; }
.gc-track { display: grid; grid-template-columns: 8.5rem 9rem 1fr 7.5rem; gap: 1rem; align-items: center;
  padding: .55rem 0; border-top: 1px solid var(--rule); }
.gc-track:first-child { border-top: 0; }
.gc-read .gc-track { grid-template-columns: 5rem 1fr; padding: .2rem 0; border: 0; }
.stApp .gc-sym, .stApp .gc-sym a { font-family: var(--serif); font-style: italic !important; font-weight: 600; font-size: 1.12rem;
  color: var(--ink) !important; text-decoration: none; }
.gc-sym a:hover { color: var(--dapi) !important; text-decoration: underline; }
.gc-type, .gc-count, .gc-lane-note { color: var(--muted); font-size: .86rem; }
.gc-count { text-align: right; font-variant-numeric: tabular-nums; }
.gc-lane { display: flex; flex-wrap: wrap; gap: 4px; }
.supported { --c: var(--v-supported); }
.partial { --c: var(--v-partial); }
.unsupported { --c: var(--v-unsupported); }
.invalid_id { --c: var(--v-invalid_id); }
.unchecked { --c: var(--v-unchecked); }
.gc-seg { display: inline-block; width: 2.2rem; height: .95rem; border-radius: 2px; background: var(--c);
  box-shadow: 0 0 10px -1px color-mix(in srgb, var(--c) 55%, transparent); }
.gc-legend .gc-seg { width: 1.3rem; height: .75rem; }
.gc-seg.invalid_id { background: repeating-linear-gradient(135deg, var(--c) 0 3px, var(--panel-solid) 3px 5px); }
.gc-seg.unchecked { background: transparent; border: 1.5px dashed var(--c); box-shadow: none; }

.gc-gene { border-top: 2px solid var(--dapi); margin-top: 3rem; padding-top: 1rem; scroll-margin-top: 4rem; }
.gc-gene-sym { font-family: var(--serif); font-style: italic; font-weight: 600; font-size: 2.3rem; line-height: 1.1; }
.gc-gene-name { color: var(--muted); font-size: 1.05rem; margin-left: .75rem; }
.gc-facts { display: flex; flex-wrap: wrap; gap: .3rem 1.5rem; color: var(--muted); font-size: .88rem; margin: .5rem 0 1rem; }
.gc-note { color: var(--muted); border-left: 3px solid var(--rule); padding-left: .85rem; max-width: 44rem; margin: 0 0 1rem; }

.gc-claim { display: grid; grid-template-columns: 9.5rem 1fr; gap: 1.1rem; padding: .95rem 1.1rem;
  background: var(--panel); border-radius: 8px; margin-bottom: .5rem; }
.gc-verdict { color: var(--c); font-weight: 600; font-size: .86rem; line-height: 1.3; border-left: 4px solid var(--c);
  padding-left: .6rem; align-self: start; }
.gc-verdict.invalid_id { border-left-style: dotted; }
.gc-verdict.unchecked { border-left-style: dashed; }
.gc-claim-text { font-family: var(--serif); font-size: 1.08rem; line-height: 1.6; max-width: 46rem; }
.gc-cites { font-size: .86rem; margin-top: .4rem; }
.gc-missing { color: var(--v-invalid_id); text-decoration: line-through; }
.gc-reason { color: var(--muted); font-size: .88rem; line-height: 1.5; margin-top: .3rem; max-width: 46rem; }

.gc-ev { padding: .7rem 0; border-top: 1px solid var(--rule); }
.gc-ev:first-child { border-top: 0; }
.gc-ev-head { color: var(--muted); font-size: .95rem; }
.gc-ev-title { font-weight: 600; font-size: 1.12rem; margin: .2rem 0; }
.gc-ev-text { font-size: 1.02rem; line-height: 1.6; max-width: 48rem; color: #C9D2E0; }

@media (max-width: 700px) {
  .gc-word { font-size: 3rem; }
  .gc-track { grid-template-columns: 1fr auto; row-gap: .35rem; }
  .gc-type { display: none; }
  .gc-lane { grid-column: 1 / -1; grid-row: 2; }
  .gc-claim { grid-template-columns: 1fr; gap: .4rem; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# Small helpers
# ---------------------------------------------------------


def esc(text: str | None) -> str:
    """Text from APIs and the LLM, shown literally inside HTML (no tags, no Markdown/LaTeX)."""
    return html.escape(text or "").replace("$", "&#36;").replace("\n", " ")


def html_block(parts: list[str]) -> None:
    """Render HTML without blank lines or indentation, so Markdown leaves it alone."""
    st.markdown("".join(parts), unsafe_allow_html=True)


def anchor(symbol: str) -> str:
    """HTML id of a gene card, safe for symbols like LINC02210-CRHR1."""
    return "gene-" + re.sub(r"[^A-Za-z0-9]+", "-", symbol)


def plural(n: int, word: str) -> str:
    """ "1 gene", "3 genes"."""
    return f"{n} {word}{'' if n == 1 else 's'}"


def source_group(source: str) -> str:
    """amass_genecore / amass_biomedcore count as one source, AMASS."""
    return "amass" if source.startswith("amass") else source


def seg(verdict: str) -> str:
    """One coloured block for one claim, with its verdict as tooltip."""
    label, meaning = VERDICTS[verdict]
    return f'<span class="gc-seg {verdict}" ' f'title="{label}: {meaning}"></span>'


# ---------------------------------------------------------
# Pipeline (unchanged logic)
# ---------------------------------------------------------


def run_analysis(
    genes: list[str],
    enabled_sources: set[str],
) -> dict:
    """
    Run retrieval for all genes.

    If an LLM API key is configured, also run the existing
    synthesizer and verifier pipeline.

    Retrieval results survive even if synthesis fails.
    """

    records = []
    verified_by_gene = {}

    source_errors = {}
    pipeline_errors = {}
    gene_names = {}

    llm_configured = bool(os.getenv("LLM_API_KEY"))

    progress = st.progress(
        0.0,
        text="Starting analysis...",
    )

    total = len(genes)

    seen_resolved_symbols = set()

    for index, symbol in enumerate(
        genes,
        start=1,
    ):
        progress.progress(
            (index - 1) / total,
            text=(f"Retrieving evidence for " f"{symbol} " f"({index}/{total})..."),
        )

        # Start with the uploaded symbol.
        # Once resolution succeeds, this is replaced by the
        # canonical human gene symbol returned by MyGene.
        resolved_symbol = symbol

        try:
            gene_info = resolve_gene_id(symbol)

            resolved_symbol = gene_info.get("symbol") or symbol

            if resolved_symbol in seen_resolved_symbols:
                progress.progress(
                    index / total,
                    text=(
                        f"Skipped duplicate " f"{resolved_symbol} " f"({index}/{total})"
                    ),
                )
                continue

            seen_resolved_symbols.add(resolved_symbol)

            gene_names[resolved_symbol] = gene_info.get("name")

            raw = collect_evidence(
                gene_info,
                enabled_sources=enabled_sources,
            )

            record = GeneRecord.model_validate(raw)

            records.append(record)

            errors = raw.get(
                "errors",
                [],
            )

            if errors:
                source_errors[resolved_symbol] = errors

        except Exception as exc:
            pipeline_errors[resolved_symbol] = [
                "Retrieval failed: " f"{type(exc).__name__}: " f"{exc}"
            ]

            progress.progress(
                index / total,
                text=(f"Finished {index}/{total}"),
            )
            continue

        # ---------------------------------------------
        # LLM synthesis + verification
        # ---------------------------------------------

        if llm_configured:
            progress.progress(
                (index - 0.45) / total,
                text=(f"Synthesizing and verifying " f"{resolved_symbol}..."),
            )

            try:
                synth = synthesize(record)

                verified = verify(
                    synth,
                    record,
                    use_llm=True,
                )

                verified_by_gene[resolved_symbol] = verified

            except Exception as exc:
                pipeline_errors.setdefault(
                    resolved_symbol,
                    [],
                ).append(
                    (
                        "Synthesis or verification "
                        "failed: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    )
                )

        progress.progress(
            index / total,
            text=(f"Finished {index}/{total}"),
        )

    progress.empty()

    return {
        "genes": list(genes),
        "records": records,
        "verified_by_gene": (verified_by_gene),
        "source_errors": source_errors,
        "pipeline_errors": (pipeline_errors),
        "gene_names": gene_names,
        "enabled_sources": set(enabled_sources),
        "llm_configured": (llm_configured),
    }


# ---------------------------------------------------------
# Results: summary sentence, claim tracks, gene sections
# ---------------------------------------------------------


def summary_sentence(records: list[GeneRecord], analysis: dict) -> str:
    """One sentence above the results: number of claims per verdict and genes without claims."""
    verified = [analysis["verified_by_gene"].get(r.gene.symbol) for r in records]
    genes = plural(len(records), "gene")
    if not analysis["llm_configured"]:
        return (
            f"Evidence retrieved for {genes}. No claims were written, "
            "because no LLM_API_KEY is set on this machine."
        )

    n = Counter(c.verdict for v in verified if v for c in v.claims)
    total = sum(n.values())
    if not total:
        return f"No claims for {genes}: too little evidence was found."

    parts = [f"{n['supported']} backed by their cited source"]
    if n["partial"]:
        parts.append(f"{n['partial']} only partly")
    if n["unsupported"]:
        parts.append(f"{n['unsupported']} not at all")
    if n["invalid_id"]:
        parts.append(f"{n['invalid_id']} cite a source that was never retrieved")
    if n["unchecked"]:
        parts.append(f"{n['unchecked']} could not be checked")
    listing = (
        parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    )
    text = f"{plural(total, 'claim')} on {genes}: {listing}."

    silent = sum(1 for v in verified if v is None or not v.claims)
    if silent:
        text += f" {plural(silent, 'gene')} without claims, see below."
    return text


def render_tracks(records: list[GeneRecord], analysis: dict) -> None:
    """Overview: one row per gene, one coloured block per claim, linked to the gene card."""
    legend = "".join(f"<span>{seg(v)}{VERDICTS[v][0]}</span>" for v in VERDICTS)
    rows = []
    for r in records:
        sym = r.gene.symbol
        v = analysis["verified_by_gene"].get(sym)
        if v and v.claims:
            lane = "".join(seg(c.verdict) for c in v.claims)
        elif not r.gene.found:
            lane = '<span class="gc-lane-note">Symbol not found</span>'
        elif v:
            lane = '<span class="gc-lane-note">No claims: too little evidence</span>'
        elif sym in analysis["pipeline_errors"]:
            lane = '<span class="gc-lane-note">Claims could not be written</span>'
        else:
            lane = '<span class="gc-lane-note">Evidence only</span>'
        rows.append(
            '<div class="gc-track">'
            f'<div class="gc-sym"><a href="#{anchor(sym)}">{esc(sym)}</a></div>'
            f'<div class="gc-type">{esc(r.gene.gene_type or "")}</div>'
            f'<div class="gc-lane">{lane}</div>'
            f'<div class="gc-count">{plural(len(r.evidence), "source")}</div>'
            "</div>"
        )
    html_block(
        [
            f'<div class="gc-legend">{legend}</div>',
            '<div class="gc-tracks">',
            *rows,
            "</div>",
        ]
    )


def render_claims(verified, record: GeneRecord, only_review: bool) -> None:
    """Claims of one gene with status, verifier reason and source links (only_review: hide supported)."""
    by_id = {e.id: e for e in record.evidence}
    claims = [c for c in verified.claims if not only_review or c.verdict != "supported"]
    rows = []
    for c in claims:
        cites = []
        for eid in c.evidence_ids:
            e = by_id.get(eid)
            if e and e.url:
                cites.append(f'<a href="{esc(e.url)}" target="_blank">{esc(eid)}</a>')
            elif e:
                cites.append(esc(eid))
            else:
                cites.append(
                    f'<span class="gc-missing" title="Not retrieved for this gene">{esc(eid)}</span>'
                )
        reason = esc(c.reason)
        if c.reason.startswith(JUDGE_FAILED):
            reason += (
                " Run the analysis again to retry: claims that were already "
                "checked come from the cache."
            )
        label = VERDICTS[c.verdict][0]
        rows.append(
            '<div class="gc-claim">'
            f'<div class="gc-verdict {c.verdict}">{label}</div>'
            "<div>"
            f'<div class="gc-claim-text">{esc(c.text)}</div>'
            f'<div class="gc-cites">{", ".join(cites)}</div>'
            + (f'<div class="gc-reason">Verifier: {reason}</div>' if reason else "")
            + "</div></div>"
        )
    html_block(rows)


def render_evidence(record: GeneRecord, verified) -> None:
    """All retrieved evidence of one gene, each marked with the claims that cite it."""
    cited_by = {}
    for i, c in enumerate(verified.claims if verified else [], 1):
        for eid in c.evidence_ids:
            cited_by.setdefault(eid, []).append(str(i))

    with st.expander(f"Retrieved evidence ({len(record.evidence)})"):
        if not record.evidence:
            st.write("Nothing was found in the selected sources.")
            return
        items = []
        for e in record.evidence:
            name = SOURCES.get(source_group(e.source), (e.source,))[0]
            eid = (
                f'<a href="{esc(e.url)}" target="_blank">{esc(e.id)}</a>'
                if e.url
                else esc(e.id)
            )
            used = (
                f", cited by claim {', '.join(cited_by[e.id])}"
                if e.id in cited_by
                else ""
            )
            items.append(
                '<div class="gc-ev">'
                f'<div class="gc-ev-head">{esc(name)}, {eid}{used}</div>'
                + (f'<div class="gc-ev-title">{esc(e.title)}</div>' if e.title else "")
                + (f'<div class="gc-ev-text">{esc(e.text)}</div>' if e.text else "")
                + "</div>"
            )
        html_block(items)


def render_gene(record: GeneRecord, analysis: dict, only_review: bool) -> None:
    """Card of one gene: header (type, IDs, evidence level, note), claims, retrieval warnings, evidence."""
    g = record.gene
    verified = analysis["verified_by_gene"].get(g.symbol)
    name = analysis["gene_names"].get(g.symbol)

    facts = []
    if not g.found:
        facts.append("Symbol not found in MyGene.info")
    if g.gene_type:
        facts.append(esc(g.gene_type))
    if g.ensembl_id:
        facts.append(
            f'<a href="https://www.ensembl.org/Homo_sapiens/Gene/Summary?g={esc(g.ensembl_id)}" '
            f'target="_blank">Ensembl {esc(g.ensembl_id)}</a>'
        )
    if g.entrez_id:
        facts.append(
            f'<a href="https://www.ncbi.nlm.nih.gov/gene/{esc(g.entrez_id)}" '
            f'target="_blank">NCBI Gene {esc(g.entrez_id)}</a>'
        )
    if verified:
        facts.append(f"Evidence {verified.evidence_level}")
    facts.append(f"{plural(len(record.evidence), 'source')} retrieved")

    html_block(
        [
            f'<div class="gc-gene" id="{anchor(g.symbol)}">',
            f'<span class="gc-gene-sym">{esc(g.symbol)}</span>',
            f'<span class="gc-gene-name">{esc(name)}</span>' if name else "",
            '<div class="gc-facts">',
            *(f"<span>{f}</span>" for f in facts),
            "</div>",
            (
                f'<div class="gc-note">{esc(verified.note)}</div>'
                if verified and verified.note
                else ""
            ),
            "</div>",
        ]
    )

    if verified and verified.claims:
        render_claims(verified, record, only_review)
    elif not analysis["llm_configured"]:
        st.caption("No claims written: no LLM_API_KEY is set on this machine.")
    elif g.symbol in analysis["pipeline_errors"]:
        st.caption("Evidence was retrieved, but the claims could not be written.")

    warnings = [
        f"{e.get('source', 'source')}: {e.get('message', '')}"
        for e in analysis["source_errors"].get(g.symbol, [])
    ] + analysis["pipeline_errors"].get(g.symbol, [])
    if warnings:
        with st.expander(f"Warnings ({len(warnings)})"):
            for w in warnings:
                st.text(w)

    render_evidence(record, verified)


# ---------------------------------------------------------
# Page: header and inputs
# ---------------------------------------------------------

EXAMPLE_LIST = Path(__file__).parent / "test_data" / "eval_genes.txt"

EXAMPLE_TRACKS = [
    ("IRGM", ["supported"] * 5),
    ("ANO3", ["supported"] * 4 + ["partial"]),
]

COLUMNS = [1.2, 1]  # same for both rows, so the right-hand panels have the same width

intro_col, read_col = st.columns(COLUMNS, gap="large")
with intro_col:
    html_block(
        [
            '<div class="gc-word">gencite</div>',
            '<p class="gc-lede">Cited, verified summaries for every gene on your list.</p>',
            '<p class="gc-fine">gencite looks up each gene in PubMed, Open Targets, the '
            "Human Protein Atlas and AMASS, writes short claims from what it finds, and "
            "has a second model check every claim against the source it cites. "
            "Human genes only.</p>",
        ]
    )
with read_col:
    with st.container(border=True, key="panel_read"):
        example = "".join(
            '<div class="gc-track">'
            f'<div class="gc-sym">{sym}</div>'
            f'<div class="gc-lane">{"".join(seg(v) for v in verdicts)}</div>'
            "</div>"
            for sym, verdicts in EXAMPLE_TRACKS
        )
        legend = "".join(
            f"<span>{seg(v)}{label}: {meaning.lower()}</span>"
            for v, (label, meaning) in VERDICTS.items()
        )
        html_block(
            [
                '<div class="gc-read">',
                '<div class="gc-read-h">Reading the results</div>',
                example,
                f'<div class="gc-legend">{legend}</div>',
                "<p>One row per gene, one block per claim. Click a gene to read its "
                "claims with their sources.</p>",
                "</div>",
            ]
        )

st.write("")
input_col, source_col = st.columns(COLUMNS, gap="large")

with input_col:
    with st.container(border=True, key="panel_list", height="stretch"):
        html_block(['<div class="gc-h"><span class="gc-step">1</span>Gene list</div>'])
        uploaded_file = st.file_uploader(
            "A .txt file with one gene symbol per line",
            type=["txt"],
            help="A header line, comments, blank lines and duplicates are removed.",
        )
        if st.button("Try the example list (8 genes)"):
            st.session_state["use_example"] = True

        genes = []
        if uploaded_file is not None:
            st.session_state["use_example"] = False
            try:
                genes = parse_gene_list(uploaded_file.getvalue().decode("utf-8-sig"))
            except UnicodeDecodeError:
                st.error(
                    "This file is not UTF-8 text. Save it as plain text and upload it again."
                )
            else:
                if not genes:
                    st.warning("No gene symbols found in this file.")
        elif st.session_state.get("use_example"):
            genes = parse_gene_list(EXAMPLE_LIST.read_text(encoding="utf-8"))

        if genes:
            st.caption(f"{plural(len(genes), 'gene')}: {', '.join(genes)}")

with source_col:
    with st.container(border=True, key="panel_sources", height="stretch"):
        html_block(
            ['<div class="gc-h"><span class="gc-step">2</span>Evidence sources</div>']
        )
        selected_sources = {
            key
            for key, (name, what) in SOURCES.items()
            if st.checkbox(name, value=True, help=what, key=f"src_{key}")
        }
        st.caption("Gene IDs always come from MyGene.info.")

if "amass" in selected_sources and not os.getenv("AMASS_API_KEY"):
    st.warning(
        "AMASS is selected, but AMASS_API_KEY is not set. "
        "The other sources still run; untick AMASS to hide this."
    )

if not os.getenv("LLM_API_KEY"):
    st.info(
        "No LLM_API_KEY is set, so gencite will retrieve evidence but not write "
        "or check claims. Add the key to .env and restart the app."
    )

if not selected_sources:
    st.warning("Select at least one evidence source.")

if not genes:
    st.caption("Upload a gene list or try the example list to start.")

if st.button(
    "Analyse genes",
    type="primary",
    use_container_width=True,
    disabled=not genes or not selected_sources,
):
    st.session_state["gencite_analysis"] = run_analysis(
        genes=genes, enabled_sources=selected_sources
    )


# ---------------------------------------------------------
# Page: results
# ---------------------------------------------------------

analysis = st.session_state.get("gencite_analysis")

# Results belong to the gene list and sources they were run with.
# If the file or the source selection changed since, drop them
# instead of showing them next to the new inputs.
if analysis and (
    analysis["genes"] != genes or analysis["enabled_sources"] != selected_sources
):
    del st.session_state["gencite_analysis"]
    analysis = None
    st.info(
        "The gene list or the source selection changed. "
        "Click Analyse genes to run the analysis again."
    )

if analysis:
    records = analysis["records"]
    failed = [
        s
        for s in analysis["pipeline_errors"]
        if s not in {r.gene.symbol for r in records}
    ]

    if not records:
        st.error("None of the genes could be processed. Details below.")
    else:
        html_block(
            [f'<p class="gc-summary">{esc(summary_sentence(records, analysis))}</p>']
        )
        render_tracks(records, analysis)

        verified_results = [
            analysis["verified_by_gene"][r.gene.symbol]
            for r in records
            if r.gene.symbol in analysis["verified_by_gene"]
        ]
        show_col, download_col = st.columns([3, 1], vertical_alignment="bottom")
        with show_col:
            view = st.segmented_control(
                "Show",
                ["All claims", "Only claims to review"],
                default="All claims",
            )
        with download_col:
            if verified_results:
                st.download_button(
                    "Download report",
                    data=build_report(
                        verified_results, {r.gene.symbol: r for r in records}
                    ),
                    file_name="gencite_report.md",
                    mime="text/markdown",
                    use_container_width=True,
                )

        only_review = view == "Only claims to review"
        shown = records
        if only_review:
            shown = [
                r
                for r in records
                if any(
                    c.verdict != "supported"
                    for c in getattr(
                        analysis["verified_by_gene"].get(r.gene.symbol), "claims", []
                    )
                )
            ]
            if not shown:
                st.caption("Every claim is supported by its cited source.")

        for record in shown:
            render_gene(record, analysis, only_review)

    if failed:
        with st.expander(f"Genes that could not be processed ({len(failed)})"):
            for symbol in failed:
                st.text(f"{symbol}: {' | '.join(analysis['pipeline_errors'][symbol])}")
