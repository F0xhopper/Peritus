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

/**
 * The kind as an identity, for anything that groups or filters by it.
 *
 * Several fetchers are one kind to a reader — OpenAlex and PubMed both find
 * papers, Exa and the web search both find web pages — so a filter or an icon
 * keyed on the fetcher would show "Web page" twice. This is the id the
 * Knowledge page's `?kind=` carries and the icon is chosen by; `other` is any
 * fetcher added to the API before it is added here.
 */
export type SourceKindId =
  | 'paper'
  | 'preprint'
  | 'encyclopedia'
  | 'web'
  | 'discussion'
  | 'video'
  | 'book'
  | 'pdf'
  | 'expert'
  | 'upload'
  | 'other'

const KIND_ID: Record<string, SourceKindId> = {
  openalex: 'paper',
  pubmed: 'paper',
  arxiv: 'preprint',
  wikipedia: 'encyclopedia',
  exa: 'web',
  web: 'web',
  reddit: 'discussion',
  youtube: 'video',
  gutenberg: 'book',
  pdf: 'pdf',
  thought_leader: 'expert',
  upload: 'upload',
}

const KIND_LABEL: Record<SourceKindId, string> = {
  paper: 'Paper',
  preprint: 'Preprint',
  encyclopedia: 'Encyclopedia',
  web: 'Web page',
  discussion: 'Discussion',
  video: 'Video',
  book: 'Book',
  pdf: 'PDF',
  expert: 'Expert writing',
  upload: 'Your upload',
  other: 'Other',
}

export function sourceKindId(type: string | null | undefined): SourceKindId {
  return (type && KIND_ID[type]) || 'other'
}

export function sourceKindLabel(id: SourceKindId): string {
  return KIND_LABEL[id]
}

/** `?kind=` from a URL someone may have edited: a known id, or nothing. */
export function parseSourceKindId(raw: string | null | undefined): SourceKindId | null {
  // `hasOwn`, not `in`: "toString" is *in* every object, and `?kind=toString`
  // would have been a kind.
  return raw && Object.hasOwn(KIND_LABEL, raw) ? (raw as SourceKindId) : null
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
