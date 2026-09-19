-- Migration 035: which reranker scored an answer's passages.
--
-- Chat reranks on Cohere when it can and falls back, silently, to scoring
-- windows of passages on the fast model. The two score on different scales, and
-- one relevance threshold is applied to both — so an audit sample that mixes
-- them cannot calibrate anything (docs/plans/beating-closed-book.md §3.10).
-- 'cohere', 'llm_window' or 'none'; NULL for answers audited before this column.

ALTER TABLE answer_audits ADD COLUMN IF NOT EXISTS reranker TEXT;
