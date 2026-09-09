# Screening golden sets

A golden set is a list of **human** keep/drop decisions about sources a real
build actually considered. It is the only thing that can tell a screening change
that improved the corpus from one that merely changed it.

Nothing in this directory is generated. A file whose labels were produced by a
model would measure the validator against itself, and would report agreement
that means nothing.

## Making one

**1. Capture a build.** The `sources` table stores scores but no text, and a
dropped source has no chunks, so a fixture cannot be reconstructed after the
fact. Capture has to happen during the build:

```bash
SCREENING_CAPTURE_DIR=./captures peritus build "intermittent fasting and cardiometabolic risk"
```

That writes `./captures/<expert-slug>/<job-id>.jsonl` — one line per source, as
the validator saw it — plus a `manifest.json` recording the topic, the key
concepts, the rubric version and which models were configured.

**2. Sample the sources to label.** Over-represent the band around the
threshold: that is where the errors are, and a sample drawn uniformly spends
most of its labels on sources whose verdict was never in doubt. Aim for 40–60
sources per topic, and make sure every `discovered_via` value in the capture
appears at least a few times — snowballed sources and planned ones fail
differently.

**3. Label them.** For each source, decide whether a corpus on this topic should
contain it, and say why in one line. Tag which of the topic's key concepts it
substantively covers. Judge the source, not the model's score — do not look at
the scores while labelling.

**4. Score.**

```bash
python -m peritus.eval.screening \
    src/peritus/eval/golden/screening/<topic>.json \
    --capture ./captures/<expert-slug>/<job-id>.jsonl
```

## Coverage

Start with three topics of different shape, because screening fails differently
in each:

| Shape | Why it is here |
|---|---|
| biomedical | dense literature, strong identifiers, abstracts everywhere; tests whether the validator can tell a good trial from a weak one |
| humanities | primary texts and commentary read alike in a snippet; tests the primary/secondary/tertiary distinction |
| practitioner craft | the best material is often a blog post or a forum thread with no scholarly apparatus at all; tests whether "credible" collapses into "academic" |

## Schema

```json
{
  "topic": "intermittent fasting and cardiometabolic risk",
  "key_concepts": ["time-restricted eating", "insulin sensitivity", "..."],
  "captured_from": "<expert-slug>/<job-id>.jsonl",
  "labels": [
    {
      "url": "https://doi.org/10.1234/example",
      "decision": "keep",
      "reason": "randomised trial reporting the primary endpoint directly",
      "labeller": "human",
      "covered_concepts": ["time-restricted eating", "insulin sensitivity"]
    }
  ]
}
```

`decision` is `keep` or `drop`; anything else is rejected when the file loads.
`url` is matched with the same normalisation the pipeline de-duplicates with, so
a trailing slash or a tracking parameter will not cause a miss.

## Reading the result

Report precision **and** recall, never accuracy alone. The two errors are not
symmetric: low precision puts junk in the corpus, where it is at least visible;
low recall throws away good sources, and nobody ever sees the paper that was not
kept.

Kappa is the number to publish. A validator that keeps 90% of everything agrees
with a human 90% of the time on a set that is 90% keeps, while exercising no
judgement at all — kappa subtracts exactly that.

Record each run in the changelog table at the end of
`docs/plans/corpus-quality.md`, with the rubric version and the models, so two
runs can be compared without ambiguity about what produced them.
