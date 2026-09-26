# gencite


## Motivation

Almost every omics analysis ends with a gene list that someone has to interpret: selection scans, RNA-seq, GWAS loci, CRISPR screens. Today that usually means looking up each gene by hand in PubMed and gene databases, which is slow. Asking a plain LLM instead is fast, but its answers cannot be traced back to a source and it invents citations.

## Goal

gencite does the lookup and a first written summary for every gene, and makes each statement checkable:

- **Every claim cites evidence.** The LLM may only use the retrieved evidence, and every claim names the PubMed, Open Targets or Human Protein Atlas record it is based on.
- **Every citation is checked in code.** A claim that cites an ID not retrieved for that gene is flagged (`invalid_id`).
- **Every claim is checked against its source.** A second LLM call (the judge) reads the claim and only the evidence it cites, and rates it `supported`, `partial` or `unsupported` with a one-line reason.
- **Honest about missing evidence.** Genes without usable evidence (unresolved symbols, most pseudogenes) get no claims and a note that says why.

The result is one Markdown report that a scientist can read and verify, with a link to every source.

## How it works

![gencite_pipeline](img/pipeline_flowchart.svg)

| Step | What happens | Data source | Code |
|---|---|---|---|
| Process input file | read the list; header line, comments, blanks and duplicates are removed | – | `inputs.py` |
| Get gene ID & gene type | symbol → Ensembl / Entrez ID and gene type. Symbol not found → evidence level `none`, no LLM call | MyGene.info | `ids.py` |
| Retrieve evidence | top 5 abstracts that mention the gene | PubMed (NCBI E-utilities) | `pubmed_retrieval.py` |
| | gene biotype and top 5 disease associations | Open Targets | `opentargets.py` |
| | tissue and cell-type expression, biological process, molecular function, disease involvement | Human Protein Atlas | `hpa_retrieval.py` |
| Evidence record per gene | all items of a gene, each with an ID (`PMID:…`, `OT:…`, `HPA:…`). No evidence → `none`, no LLM call | – | `collect_evidence.py` |
| **Synthesizer** (LLM) | up to 5 short claims, each citing evidence IDs, plus an evidence level `sufficient` / `limited` / `none` | LLM | `synth_LLM.py` |
| Verifier 1 · ID check | every cited ID must be in this gene's evidence, otherwise `invalid_id` (`X`) and the claim is not judged | – | `verify.py` |
| **Verifier 2 · Judge** (LLM) | reads the claim and only the evidence it cites → `supported` / `partial` / `unsupported` with a one-line reason | LLM (can be a different model) | `verify.py` |
| Gene report | summary table + one section per gene: gene type, claims, status, source links, all retrieved evidence | – | `create_report.py` |

Retrieval sources are independent: if one fails or has no entry for a gene (e.g. a pseudogene missing in the Human Protein Atlas), the gene continues with the others.

## Requirements

- Python 3.10 or newer
- Internet access to MyGene.info, NCBI E-utilities, the Open Targets API and the Human Protein Atlas (all free, no key needed)
- An API key for an OpenAI-compatible LLM endpoint (DeepSeek, Groq, Gemini, OpenAI, a local Ollama server, …)

Python packages (`requirement.txt`):

| Package | Used for |
|---|---|
| `requests` | MyGene.info, PubMed, Open Targets and Human Protein Atlas calls |
| `openai` | LLM calls (any OpenAI-compatible endpoint) |
| `pydantic` | data schemas and validation of the LLM output |
| `python-dotenv` | reading the configuration from `.env` |

## Installation

```bash
git clone https://github.com/nomis-c/gencite.git
cd gencite
python3 -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirement.txt
```

## Configuration

There is no config file. Settings live in two places:

- **`.env`** for the LLM endpoint, model and key (per machine, never committed)
- **command-line flags** for everything that changes per run (see [Usage](#usage))

```bash
cp .env.example .env               # then fill in LLM_API_KEY
```

| Variable | Required | Meaning |
|---|---|---|
| `LLM_BASE_URL` | no (default `https://api.deepseek.com`) | endpoint for the synthesizer |
| `LLM_MODEL` | no (default `deepseek-chat`) | model for the synthesizer |
| `LLM_API_KEY` | **yes** | API key |
| `JUDGE_BASE_URL`, `JUDGE_MODEL`, `JUDGE_API_KEY` | no | a different model as judge; each empty value falls back to `LLM_*` |
| `GENCITE_NO_CACHE` | no | `1` turns the cache off (same as `--no-cache`) |

## Usage

Run the whole pipeline on the example list (15 genes, about 3–4 minutes on the first run):

```bash
python cli.py test_data/gene_list.txt
```

Then open `results/gene_list/report.md` (e.g. in the PyCharm or VS Code Markdown preview).

Your own list is a text file with one gene symbol per line. A header line such as `Gene` or `Symbol` is detected and skipped.

### Commands

| Command | What it does |
|---|---|
| `python cli.py <genes.txt>` | whole pipeline, gene list → report, results in `results/<list name>/` |
| `python cli.py <genes.txt> --out results/my_run` | write to another folder |
| `python cli.py <genes.txt> --no-judge` | skip verifier 2 (judge), claims get `?`, fewer LLM calls |
| `python cli.py <genes.txt> --no-cache` | ask the LLM again instead of using cached answers |
| `python cli.py <records folder>` | synthesizer → report on saved evidence (no retrieval), e.g. `results/gene_list/records` |
| `python cli.py --help` | all options |
| `python clean.py` | delete all results, the LLM cache and Python bytecode (`--keep-cache`, `--dry-run`) |
| `python cache.py` / `python cache.py --clear` | show / delete only the LLM cache in `data/cache/` |

Single steps, e.g. to look at the prompts or rerun one stage (default output: `results/steps/`):

| Step | Command |
|---|---|
| Synthesizer | `python synth_LLM.py <records> [--out DIR] [--dry-run]` |
| Verifier 1 + 2 | `python verify.py <synth> <records> [--out DIR] [--no-llm] [--dry-run]` |
| Gene report | `python create_report.py <verified> <records> [--out FILE]` |

`--dry-run` prints the LLM prompts without calling the LLM, `--no-llm` runs only verifier 1 (ID check).

### Output

Everything the pipeline generates goes to `results/`. Each run gets its own folder, named after the input (`results/gene_list/` for `test_data/gene_list.txt`). A new run of the same input first deletes the old results in that folder, so genes from different runs never mix.

`results/<name>/`:

| Path | Content |
|---|---|
| `records/` | retrieved evidence per gene (JSON), only when the input is a gene list |
| `synth/` | claims with the cited evidence IDs (JSON) |
| `verified/` | claims with status and the judge's reason (JSON) |
| `report.md` | summary table and one section per gene: gene type, Ensembl link, evidence level, claims with status, source links, and all retrieved evidence marked "cited" or "not cited" |

Claim status in the report:

| Mark | Status | Meaning |
|---|---|---|
| `+` | supported | the cited evidence states the claim |
| `~` | partial | only part is backed, or the claim overstates it (e.g. association → causation, mouse → human) |
| `-` | unsupported | the cited evidence does not back the claim |
| `X` | invalid_id | the claim cites an ID that was not retrieved for this gene |
| `?` | unchecked | the judge was skipped (`--no-judge`) or its call failed |

Exit code 1 means some genes or claims failed, usually because of an LLM rate limit. Run the same command again: finished LLM calls come from the cache, only the failed ones are repeated.

## Testing

`test_data/` is the test data set:

| Path | Content | Used by |
|---|---|---|
| `test_data/gene_list.txt` | 15 real genes | whole pipeline with live retrieval: `python cli.py test_data/gene_list.txt` |
| `test_data/dummy_records/` | hand-written evidence for 6 genes with made-up PMIDs, incl. traps (a readthrough whose evidence is about its partner gene, a pseudogene, an unresolved symbol) | synthesizer → report without retrieval: `python cli.py test_data/dummy_records` |
| `test_data/synth_bad/` | deliberately wrong claims | verifier test: `python verify.py test_data/synth_bad test_data/dummy_records` |

`test.md` lists manual checks for every part with the expected output, including a full end-to-end run (section "End-to-end run").

Clean up after testing:

```bash
python clean.py               # results/, LLM cache, __pycache__/
python clean.py --keep-cache  # keep the cache so the next run is fast and free
```

## Project structure

```
cli.py                 entry point: whole pipeline
inputs.py              gene list parsing
ids.py                 gene ID + gene type (MyGene.info)
pubmed_retrieval.py    PubMed search + abstracts
opentargets.py         Open Targets biotype + disease associations
hpa_retrieval.py       Human Protein Atlas expression + annotation
amass_retrieval.py     AMASS GeneCore gene/protein summaries + BiomedCore literature
collect_evidence.py    evidence record per gene (all sources)
synth_LLM.py           synthesizer (LLM)
verify.py              verifier 1 (ID check) + verifier 2 (LLM judge)
create_report.py       gene report (Markdown)
schema.py              data shapes shared by all steps (pydantic)
llm_client.py          LLM calls: config from .env, retries, JSON validation, cache
cache.py               disk cache in data/cache/
clean.py               delete results, cache and bytecode
test_data/             test data set: gene list, dummy evidence, wrong claims
test.md                manual test checklist
results/               everything the pipeline generates (git-ignored)
```

## Known limitations

- Retrieval does not fetch the Open Targets function text, so many genes only get association-level claims (`limited`).
- The gene type comes straight from MyGene.info: readthroughs show as `protein-coding`, pseudogenes as `unknown`.
- The PubMed search has no filter, so reviews that only mention a gene in passing are common.
- Non-human studies are not filtered out (e.g. MYOZ3: chicken, rat, horse), and claims do not always name the species.
- Only LLM calls are cached; MyGene, PubMed, Open Targets and the Human Protein Atlas are called again on every run.
- The judge is an LLM too: it can miss an overstated claim, so `supported` means "the judge found it in the cited text", not "proven".
