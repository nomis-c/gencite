# Test data

| Path | Content |
|---|---|
| `gene_list.txt` | 15 real genes for a live run: `python cli.py test_data/gene_list.txt` |
| `dummy_records/` | 6 hand-written GeneRecords, no retrieval needed: `python cli.py test_data/dummy_records` |
| `synth_bad/` | deliberately wrong claims for the verifier: `python verify.py test_data/synth_bad test_data/dummy_records` |
| `eval_genes.txt` | evaluation set: 5 well-described genes + 3 negative controls, for gencite vs. baseline |
| `eval_expected.json` | expected terms and kind (`clear` / `negative`) per gene of `eval_genes.txt`, read by `evaluate.py` |

## `dummy_records/` – synthesizer test cases

GeneRecord JSONs (retrieval output = synthesizer input).
Gene IDs and types are real. **PMIDs (9000xxxx) and abstract texts are made up** – don't cite them.

| File | Case | Expected synth result |
|---|---|---|
| IRGM.json | rich evidence, incl. a mouse study and association-only items | `sufficient`, claims keep "associated" / "in mice" |
| SPG7.json | rich, clean evidence | `sufficient` |
| TMEM220.json | only a prediction + a passing mention in a gene list | `limited` or `none` |
| LINC02210-CRHR1.json | readthrough; evidence is mostly about CRHR1 | must not describe CRHR1 as this gene |
| MAGOH2P.json | pseudogene, no evidence | `none`, no LLM call |
| ABCXYZ.json | symbol not resolved (`found: false`) | `none`, no LLM call |

## `synth_bad/` – verifier test cases

Hand-written `SynthResult`s with deliberately wrong claims, input for `verify.py`. Expected verdicts:

| Gene | Claim | Expected |
|---|---|---|
| IRGM | ULK1/BECN1 adaptor (control) | `supported`, or `partial` (the abstract only says "suggesting") |
| IRGM | cites made-up `PMID:99999999` | `invalid_id` |
| IRGM | cites valid PMID + `OT:function:SPG7` (other gene) | `invalid_id` |
| IRGM | "Loss of IRGM causes Crohn's" (association → causation) | `unsupported` or `partial` |
| IRGM | mouse mitophagy finding stated for human patients | `partial` or `unsupported` |
| LINC02210-CRHR1 | CRHR1 antagonist result attributed to the readthrough | `unsupported` |
| LINC02210-CRHR1 | "causal gene for Parkinson's" (evidence: not resolvable) | `unsupported` |
| TMEM220 | "validated biomarker" (evidence: not validated) | `unsupported` |

## `eval_genes.txt` + `eval_expected.json` – evaluation set

Compares gencite with the baseline (same LLM without retrieval, `baseline.py`):

```bash
python cli.py test_data/eval_genes.txt        # gencite  -> results/eval_genes/
python baseline.py test_data/eval_genes.txt   # baseline -> results/eval_genes/baseline/
python evaluate.py results/eval_genes         # -> results/eval_genes/evaluation.md
```

| Gene | Kind | Why | Expected (any of the terms counts) |
|---|---|---|---|
| LCT | clear | well described | lactase, lactose |
| IRGM | clear | well described | autophagy, Crohn |
| SPG7 | clear | well described | paraplegin, spastic paraplegia |
| HBG2 | clear | well described | fetal hemoglobin, HbF, gamma-globin |
| ERAP2 | clear | well described | aminopeptidase, antigen |
| MAGOH2P | negative | pseudogene | `limited` or `none`, no invented function |
| NOC2LP2 | negative | pseudogene | `limited` or `none`, no invented function |
| ABCXYZ | negative | symbol does not exist | `none`, no claims |

`clear`: a correct summary mentions at least one expected term. `negative`: an honest answer is not rated `sufficient`.
