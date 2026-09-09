# Concept graph: which relationships are worth extracting

**Status:** implemented, September 2026. Every figure below comes from the live database
as it was when this was written (6 experts, 4,900 nodes, 5,918 edges) or from the code in
`api/src/peritus/graph/`. The proposal in §5 and §6 is now the shipped design: the five
types and their endpoint rules live in `graph/domain.py` and are enforced on both write
paths, the reconciliation pass is `graph/reconciler.py`, and `migrations/024_graph_vocabulary.sql`
maps existing graphs onto the new vocabulary and replaces `weight` with a counted
`evidence`. §2 is kept as the record of what was wrong, not as a description of the
database today.

## 1. The short version

The graph currently extracts six relationship types, but only one of them does any product
work. `contradicts` feeds the contradictions endpoint, the chat heads-up, and the dashed
lines in the graph view. The other five are rendered as a one-line annotation under each
retrieved passage and are otherwise decoration.

The six types are also the wrong six. They describe a concept ontology ("A defines B",
"A builds on B"), which is something a fast model reading ten chunks at a time cannot
assert reliably, and which the product never needs. What the product needs is an
**evidence map**: which claims the corpus makes, which sources make them, and where those
sources agree, disagree, or qualify each other.

Recommendation: keep two of the existing types with tightened meanings, add two, collapse
the rest into one, and enforce the set at ingest. Five types total.

| Type | Between | Meaning | Status |
|---|---|---|---|
| `contradicts` | claim → claim | The two propositions cannot both be true | keep, restrict endpoints, require a stated point of dispute |
| `supports` | claim → claim | A second source asserts, or gives evidence for, the same proposition | keep, restrict endpoints |
| `qualifies` | claim → claim | True, but only under a condition, population, dose, period, or scope the other claim omits | **new**: the most common real relationship in a literature |
| `about` | claim → concept | The concept a claim is a claim about | **new**: replaces `defines`, `exemplifies`, and claim→concept `builds_on` |
| `part_of` | concept → concept | Hierarchy, the only concept-to-concept edge a ten-chunk window can justify | **new**: replaces concept→concept `builds_on`, `defines`, `includes`, `contains` |

Dropped: `cites` (1.5% of edges, between concept nodes, and real citation structure already
lives in the sources ledger), `exemplifies` and `defines` (properties of a node, not edges).

## 2. What is in the database today

### 2.1 Edge types

| Type | Count | Share | Mean weight |
|---|---|---|---|
| `supports` | 1,972 | 33% | 0.86 |
| `builds_on` | 1,505 | 25% | 0.85 |
| `exemplifies` | 1,017 | 17% | 0.87 |
| `defines` | 940 | 16% | 0.90 |
| `contradicts` | 358 | 6% | 0.83 |
| `cites` | 86 | 1.5% | 0.86 |
| off-schema (`includes`, `enriches`, `affects`, `contains`, `requires`, `causes`, `interprets`, `exhibits`, `related`, `drives`, `depends_on`, `suppresses`) | 40 | 0.7% | |

Node types tell the same story. The schema allows `concept` and `claim`, but the database
holds 114 nodes typed `definition`, `example`, `argument`, or `counterargument`. The model
is leaking the `content_type` vocabulary into `node_type`, and the `content_type` column has
picked up `supports` and `exemplifies` in return.

The tool schema declares enums, but nothing enforces them. `_parse_extract_response` checks
only that the three required keys are present, and `bulk_insert_from_extractions` defaults a
missing edge type to `builds_on` rather than rejecting it. That default silently mislabels.

### 2.2 The weight carries no information

| Weight band | Edges |
|---|---|
| 0.8 to 1.0 | 4,462 (75%) |
| 0.6 to 0.8 | 1,413 (24%) |
| below 0.6 | 43 (1%) |

The retriever orders hop expansion by weight and the graph view scales line width by it.
With three quarters of edges above 0.8, neither ordering is doing anything. A model asked
for a "strength" with no definition returns its prior.

### 2.3 What each type actually contains

Random samples from the live data, with the node type of each endpoint.

**`supports` (1,972).** 819 are concept→concept, which has no meaning: a concept cannot
support a concept, only a claim can be supported.

- "Honey storage instinct" supports "Docility when honey-gorged"
- "FeatHub" supports "Feature Registry"
- "Varroa destructor" supports "Varroa suppresses host immune response"

The third one is the shape the type should always have. The first two are "related to".

**`builds_on` (1,505).** 1,209 are concept→concept. In practice it means "is near".

- "Snow load management" builds on "Rafter ties"
- "Varroa mites" builds on "Chronic Bee Paralysis Virus"

**`defines` (940).** Direction is unstable and the meaning drifts between "is a definition
of", "is a property of", and "is an instance of".

- "Animate" defines "Soul"
- "Honey bee gut microbiome" defines "Apis mellifera"
- "Ten Categories" defines "Place"

**`exemplifies` (1,017).** Mostly correct, mostly useless. A node already carries
`content_type: example`. An edge saying so twice adds nothing to retrieval.

**`cites` (86).** "Boethius" cites "Porphyry". This is the one type that is about sources
rather than ideas, and it is being asserted between concept nodes by a model that has not
seen a reference list. The sources table already records `discovered_via = snowball` and
the DOI-level reference walk. The graph should not duplicate that with a weaker version.

**`contradicts` (358).** This is the one that matters, so it deserves the closest look.

| Property | Count | Share |
|---|---|---|
| concept → concept | 162 | 45% |
| claim → concept | 94 | 26% |
| claim → claim | 50 | 14% |
| cross-source (nodes anchored on different sources) | 109 | 30% |
| within one source, or undetermined | 249 | 70% |

Samples of the concept→concept ones:

- "Hypothetical Syllogistic" contradicts "Categorical Syllogistic"
- "Grammatical Thomism" contradicts "Analytical Thomism"
- "Essence (essentia)" contradicts "Being of Reason (ens rationis)"
- "Synergistic parasite-pathogen interactions" contradicts "Apiculture"

None of these is a contradiction. They are distinctions: two things that differ, not two
statements that cannot both hold. Two concepts cannot contradict each other. Only two
propositions can. Nearly half of the product's headline signal is this category error.

The claim→claim ones look right:

- "Final cause terminates series" contradicts "Infinite Regress"
- "Baselines fail on dataset bias" contradicts "Vanilla Mahalanobis"

### 2.4 Why cross-source contradictions are rare

Only 30% of `contradicts` edges span two sources, and those are the only ones the product
can honestly call "sources in this corpus were judged to disagree". This is structural, not
a prompt problem. Extraction runs on batches of ten consecutive chunks, so almost every
batch sits inside one source. The model can only see a cross-source disagreement when a
batch straddles a source boundary, or when two separately-extracted nodes happen to merge
by label later. The pipeline is built so that the thing it most wants to find is the thing
it is least able to see.

### 2.5 Graph shape

- Hub nodes reach degree 138 ("Syllogism"), 75 ("DNA Methylation"). The per-hop cap in the
  retriever exists to contain them, but they still dominate the annotation for any passage
  they touch.
- 83 pairs have an edge in both directions. 47 pairs have more than one edge type between
  them. Neither is prevented, and neither is meaningful under the current vocabulary.
- 51 nodes have no edges at all.

## 3. What the edges are used for

Tracing every consumer of `edge_type` in the codebase:

| Consumer | What it reads | Which types matter |
|---|---|---|
| `graph/retriever.py` | Orders local edges with `contradicts` first, then by weight. Renders up to five as `A --type--> B` under the passage. Sets `has_contradiction`. | `contradicts` for the flag. The rest are text the model may or may not read. |
| `chat/agent.py` | One prompt line when `has_contradiction` is set | `contradicts` only |
| `audit/service.py` `/contradictions` | Resolves `contradicts` edges to passages, classifies cross/within source | `contradicts` only |
| `audit/service.py` `/graph` | Passes type through for rendering | dashed line for `contradicts`, label text for the rest |
| `audit/repository.py` `edge_type_breakdown` | Counts per type so contradicts has a denominator | all, as a denominator |
| `web/components/experts/knowledge-graph.tsx` | Dashed line for `contradicts`; human labels for six types | `contradicts` visually; others as tooltip text |

Five of six types have exactly one consumer: the passage annotation string. There is no
evidence that the annotation changes answers, and the eval harness does not test it.

## 4. What the graph is for

The positioning is: a vetted corpus, a record of how it was assembled, and a flag wherever
the sources inside it disagree. The graph earns its place in that story only through two
questions a researcher asks:

1. **What does this corpus claim about X, and who says so?** That needs claims anchored to
   passages (which exists: `chunk_ids`), and a link from each claim to the concept it is
   about.
2. **Where do the sources disagree, and about what exactly?** That needs claim-to-claim
   edges across sources, each with a stated point of dispute, and the third option that
   real literatures are full of: not agreement or disagreement but qualification.

Neither question is answered by a concept ontology. "Rafter ties are part of snow load
management" is true and nobody will ever ask the corpus about it.

So the design principle: **claims are the first-class node; concepts are the index into
them; edges describe the relationship between propositions, not between topics.**

## 5. The proposed set

### `contradicts` (claim → claim)

The two propositions cannot both be true. Required property: `point`, one sentence stating
what is disputed in the subject's terms ("whether Varroa alone causes colony collapse
without viral co-infection"). Both endpoints must be `claim`. Concept endpoints are
rejected at ingest.

This is the edge that feeds `/contradictions` and the chat heads-up, so it is the one to
get right. The `point` property replaces `weight` as the thing the audit page shows, and it
is what the chat prompt should pass through instead of a bare flag.

### `supports` (claim → claim)

Another source asserts the same proposition, or reports evidence for it. Both endpoints
`claim`. This is what makes "three sources agree, one disagrees" answerable, which is the
evidence-map view a scoping reviewer actually wants. Concept→concept `supports` (819 edges
today) is dropped.

### `qualifies` (claim → claim), new

The from-claim narrows the to-claim: a condition, a population, a dose, a period, a scope.
"Intermittent fasting lowers LDL" is qualified by "the effect appears only in participants
with baseline LDL above 130". This is the most common relationship between findings in any
real literature, and today the model has to force it into either `contradicts` (wrong) or
`builds_on` (meaningless). Required property: `condition`, one sentence.

For a reviewer this is the most valuable edge of the five. Contradictions are rare and
usually noise. Qualifications are where the actual state of the evidence lives.

### `about` (claim → concept), new

The concept a claim concerns. One or more per claim. Replaces `defines`, `exemplifies`, and
every claim→concept `builds_on`. This is the index: "every claim about DNA methylation" is
a single query, and the contradictions page can group disputes by concept instead of
listing edges.

### `part_of` (concept → concept), new

The one hierarchical edge. Replaces concept→concept `builds_on`, `defines`, `includes`,
`contains`. Kept because the graph view needs some structure between concepts and because
retrieval hop expansion needs something to walk. Kept to one type because a ten-chunk
window cannot distinguish "is a kind of" from "is a component of" from "is a prerequisite
for" with any reliability, and no consumer needs the distinction.

### Dropped

- `cites`: 86 edges between concepts. Citation structure is a property of sources, already
  recorded in the ledger by the snowball stage, at DOI resolution. The graph's version is a
  guess.
- `exemplifies`: the node's `content_type` already says it is an example; `about` says what
  it is an example of.
- `defines`: a definition is a node's `description`, not a relationship.
- `weight`: replaced by objective evidence counts (distinct sources on each endpoint's
  `chunk_ids`) for ordering, and by the `point` or `condition` property for display.

## 6. What has to change in the pipeline

Changing the vocabulary alone will not fix the 70% within-source figure. Three changes,
in order of importance:

1. **Enforce the schema at ingest.** Reject any edge or node whose type is not in the enum,
   and reject `contradicts`, `supports`, `qualifies` unless both endpoints are `claim`. Log
   the rejection count per build. Remove the `builds_on` default. This is a bug fix and can
   ship independently of everything else.

2. **Add a reconciliation pass after entity resolution.** Extraction within a batch should
   produce claims, `about` edges, and `part_of` edges only. Then, per concept, gather the
   claims about it from different sources and ask the model in one call which pairs
   support, contradict, or qualify each other, with the `point` or `condition` stated. This
   is the only way cross-source relationships can be seen at all, it is bounded (claims per
   concept, not chunks squared), and it produces the edges with the evidence for both sides
   already in hand. Passing the source title and type alongside each claim also lets the
   model weigh a preprint against a review, which the per-batch pass cannot.

3. **Change what the retriever passes to the chat prompt.** Today the annotation is
   `A --supports--> B` with no context. Under the new set the useful annotation for a passage
   is: the concepts it is about, and any `contradicts` or `qualifies` edge touching its
   claims, rendered as the `point` or `condition` sentence. That is evidence in the
   subject's terms, which is what the grounding contract wants, rather than a graph
   notation the model has to interpret.

### Migration

Existing experts do not need a rebuild. A one-off migration maps the old vocabulary onto
the new one where the mapping is safe and drops the rest:

| Old | Endpoints | New |
|---|---|---|
| `contradicts`, `supports` | claim → claim | unchanged |
| `contradicts`, `supports` | any concept endpoint | dropped |
| `builds_on`, `defines`, `exemplifies` | claim → concept | `about` |
| `builds_on`, `defines`, `includes`, `contains` | concept → concept | `part_of` |
| `cites`, everything else off-schema | | dropped |
| node types outside `concept`/`claim` | | `claim` if `content_type` is `argument` or `counterargument`, else `concept` |

The `/contradictions` endpoint keeps working through the migration because it only reads
claim→claim `contradicts`, which is the subset being kept.

## 7. What not to do

- Do not add more concept-to-concept types (`causes`, `requires`, `affects` are already
  leaking in). Each one is a claim about the world dressed as an ontology edge, and the
  model should be making it as a `claim` node with a passage behind it instead.
- Do not keep `weight` and try to calibrate it. There is no ground truth to calibrate
  against, and the number will always be read as confidence by a user.
- Do not let the graph become the retrieval index. Passages are retrieved; the graph
  annotates. That decision is right and nothing here changes it.
- Do not report a within-source `contradicts` as a disagreement between sources. The
  `kind` field in `/contradictions` already separates them. With the reconciliation pass,
  within-source edges become rare enough to hide by default.
