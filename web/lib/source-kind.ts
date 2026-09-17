/**
 * What a source *is*, from the search that found it.
 *
 * `source_type` is the fetcher's name — a search vendor (Exa), a database
 * (OpenAlex, PubMed), a site (Wikipedia) or a category (thought leader) — and
 * printing it as a "Type" column mixed three taxonomies as if they were one. A
 * reader wants to know whether they are looking at a paper, a video or a web
 * page; the fetcher stays available as "Found via".
 */
const KIND: Record<string, string> = {
  openalex: 'Paper',
  pubmed: 'Paper',
  arxiv: 'Preprint',
  wikipedia: 'Encyclopedia',
  exa: 'Web page',
  web: 'Web page',
  reddit: 'Discussion',
  youtube: 'Video',
  gutenberg: 'Book',
  pdf: 'PDF',
  thought_leader: 'Expert writing',
  upload: 'Your upload',
}

const PROVIDER: Record<string, string> = {
  openalex: 'OpenAlex',
  pubmed: 'PubMed',
  arxiv: 'arXiv',
  wikipedia: 'Wikipedia',
  exa: 'Exa web search',
  web: 'Web search',
  reddit: 'Reddit',
  youtube: 'YouTube',
  gutenberg: 'Project Gutenberg',
  pdf: 'PDF search',
  thought_leader: 'Expert blogs and essays',
  upload: 'Uploaded by you',
}

export function sourceKind(type: string | null | undefined): string {
  if (!type) return '—'
  return KIND[type] ?? type.replace(/[_-]+/g, ' ').replace(/^./, (c) => c.toUpperCase())
}

export function sourceProvider(type: string | null | undefined): string {
  if (!type) return '—'
  return PROVIDER[type] ?? sourceKind(type)
}

/**
 * How a source was found, as a phrase. The stored value is a key — `plan`,
 * `gapfill:<concept>`, `snowball:backward` — and printed raw in monospace it
 * read as the pipeline talking to itself.
 */
export function describeDiscovery(via: string | null | undefined): string {
  if (!via) return '—'
  if (via === 'plan') return 'Planned search'
  if (via === 'upload') return 'Added by you'
  if (via.startsWith('gapfill:')) return `Follow-up search: ${via.slice('gapfill:'.length)}`
  if (via === 'gapfill') return 'Follow-up search'
  if (via === 'snowball:backward') return 'Cited by a kept source'
  if (via === 'snowball:forward') return 'Cites a kept source'
  if (via.startsWith('snowball')) return 'Followed a citation'
  if (via.startsWith('feedback') || via.startsWith('round')) return 'Follow-up search'
  return via.replace(/[_:-]+/g, ' ').replace(/^./, (c) => c.toUpperCase())
}

/** How much of a source was read, in words. */
export function describeTextRead(method: string | null | undefined): string {
  if (!method) return '—'
  const known: Record<string, string> = {
    abstract: 'Abstract only',
    full_text: 'Full text',
    oa_pdf_url: 'Open-access PDF',
    oa_pdf_ocr: 'Open-access PDF (scanned)',
    oa_landing_url: 'Open-access web page',
    oa_landing_html: 'Open-access web page',
    landing_page_url: 'Web page',
    html: 'Web page',
    pdf: 'PDF',
    pdf_url: 'PDF',
    exa_contents: 'Web page',
    wikipedia_extract: 'Encyclopedia article',
    youtube_transcript: 'Video transcript',
    transcript: 'Transcript',
  }
  return known[method] ?? method.replace(/[_-]+/g, ' ').replace(/^./, (c) => c.toUpperCase())
}

/**
 * The validator's 1–5 difficulty, in words.
 *
 * The number alone ("Difficulty 5") is a scale the reader was never shown: 1 is
 * something you could hand a beginner, 5 needs the field's own vocabulary. The
 * number stays on the `title` for anyone who wants it.
 */
const DIFFICULTY = ['Introductory', 'Accessible', 'Intermediate', 'Advanced', 'Expert']

export function describeDifficulty(level: number | null | undefined): string {
  if (level === null || level === undefined) return '—'
  return DIFFICULTY[Math.min(Math.max(Math.round(level), 1), 5) - 1]
}

/**
 * Whether the reader may show the whole of a source, rather than a window.
 *
 * **The server decides**; this only decides whether to *offer* the action, so
 * that a reader is not sent to a page that then explains it cannot show them
 * what they clicked for. Keep it in step with `_whole_text_allowed` in
 * `api/src/peritus/api/routes/sources.py`, which is the gate that matters.
 *
 * The rule there: the kinds whose text is free to reproduce, plus anything read
 * through a resolved open-access copy (`oa_…`, the one licence fact the
 * pipeline records) — and an upload for its owner alone, because the rights
 * warning at upload was shown to the uploader and not to whoever they later
 * share the expert with.
 */
const WHOLE_TEXT_KINDS = new Set(['gutenberg', 'wikipedia', 'arxiv'])

export function mayReadWhole(
  source: { source_type: string; full_text_method?: string | null },
  isOwner: boolean
): boolean {
  const method = source.full_text_method ?? ''
  if (method === 'abstract') return false
  if (source.source_type === 'upload') return isOwner
  return WHOLE_TEXT_KINDS.has(source.source_type) || method.startsWith('oa_')
}
