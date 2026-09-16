"""The build pipeline, split by stage.

`builder.py` next door holds `ExpertBuilder` — the coordinator that runs the
stages in order and owns the state that crosses them. Everything here is the
part of a stage that needs no coordinator: the prompts and tool schemas, the
normalisers, the scoring and budget arithmetic, the event vocabulary.

The split is by *stage*, not by kind, because that is how a build is debugged:
"the plan came back wrong" and "the wrong sources were fetched" send you to
different files.
"""
