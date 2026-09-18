/**
 * Hand-written mirror of `api/src/peritus/api/schemas/*.py` and the plain dicts
 * the audit service returns. There is no codegen step, so the fixtures in
 * `tests/fixtures/` are type-checked against these interfaces — a payload shape
 * that drifts fails `tsc` rather than failing at runtime in a user's browser.
 *
 * Where the API returns `value | null` to mean "not recorded", the type is
 * `| null` and the UI must render "not recorded", never a zero (audit-api.md).
 */

// ── enums ───────────────────────────────────────────────────────────────────

export type ExpertStatus = 'queued' | 'building' | 'ready' | 'failed'

/**
 * Retrieval readiness. An expert answers from `chat_ready` onward — a whole
 * stage before `status` becomes 'ready' — so every chat affordance gates on
 * this and never on `status`.
 */
export type Readiness = 'pending' | 'chat_ready' | 'graph_ready'

export type ExpertTier = 'lite' | 'standard' | 'pro'

export type SourceDecision = 'all' | 'accepted' | 'rejected'

export type SourceSort =
  'decision' | 'quality' | 'relevance' | 'title' | 'type' | 'discovered_via' | 'added'

export type ExportFormat = 'csv' | 'ris'

/** `public` is the admin-curated catalog. Sharing a private expert is a link
 *  (`ShareState`), never a visibility — a slug is guessable. */
export type Visibility = 'private' | 'public'

/**
 * The caller's relationship to an expert they can read. A viewer opened a share
 * link (or reads a public expert): they can read and ask, and every control that
 * changes the expert is hidden. The API re-checks ownership on every mutation;
 * this only decides what to render. See `lib/access.ts`.
 */
export type ExpertAccess = 'owner' | 'viewer'

export const TIERS: readonly ExpertTier[] = ['lite', 'standard', 'pro']

// ── auth ────────────────────────────────────────────────────────────────────

export interface Me {
  id: string
  email: string | null
  is_admin: boolean
}

/** One way into the account. `provider` is `email` or `google`. */
export interface Identity {
  id: string
  provider: string
  email: string | null
  created_at: string | null
  last_sign_in_at: string | null
}

/** The signed-in person's own account, for Settings. */
export interface Account {
  id: string
  email: string | null
  /** An address change waiting for its confirmation code. */
  new_email: string | null
  name: string | null
  avatar_url: string | null
  is_admin: boolean
  /** null: this server cannot tell (no Supabase `auth` schema, local dev). */
  has_password: boolean | null
  email_confirmed: boolean
  identities: Identity[]
  created_at: string | null
  last_sign_in_at: string | null
}

/** One signed-in device. `current` is the one making the request. */
export interface SignInSession {
  id: string
  current: boolean
  created_at: string
  last_active_at: string | null
  /** The browser or app, as it was when the session began. */
  user_agent: string | null
}

export interface EmailChangeResult {
  complete: boolean
  session: Session | null
  message: string | null
}

export interface SignupResult {
  confirmation_required: boolean
  session: Session | null
}

export interface Session {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  expires_at: number | null
  user: { id: string; email?: string | null }
}

export interface AuthStatus {
  auth_enabled: boolean
  login_available: boolean
}

// ── experts ─────────────────────────────────────────────────────────────────

export interface ExpertSummary {
  id: number
  /** The slug. `experts.name` is the URL segment; there is no separate name. */
  name: string
  topic: string
  status: ExpertStatus
  /** Whether a build job is actually queued or running. `status` alone can say
   *  queued for an expert whose job no longer exists. Absent from older servers. */
  build_active?: boolean | null
  tier: ExpertTier
  readiness: Readiness
  graph_expanded: boolean
  persona_name: string | null
  persona_bio: string | null
  persona_style: string | null
  avg_quality: number | null
  key_concepts: string[]
  source_count: number
  chunk_count: number
  node_count: number
  edge_count: number
  source_type_counts: Record<string, number>
  /** The owner's chosen avatar, or null for "derive it from the persona name"
   *  — which is what every expert is until someone changes it. */
  avatar: ExpertAvatar | null
  /** The picture found for this expert's subject, or null. Outranked by
   *  `avatar`; outranks the derived monogram. See `lib/avatar.ts`. */
  picture: ExpertPicture | null
  /** Absent from older servers, which only ever returned the caller's own. */
  access?: ExpertAccess
  created_at: string
}

/** A rendering recipe, not an image. See `lib/avatar.ts`. */
export interface ExpertAvatar {
  style: string
  seed: string | null
  hue: number | null
}

/**
 * A found, licensed picture of what the expert is *about* — not a headshot of
 * its persona, and not uploaded by anyone.
 *
 * The bytes are at `/api/experts/{name}/picture?v={version}`; `version` is the
 * image's short content hash, which is what makes that URL safe to cache
 * immutably. Everything else here is provenance, and it is not decoration: when
 * `attribution_required` is true the licence obliges us to name the artist and
 * link `file_page_url` wherever the picture is the identity of a page.
 */
export interface ExpertPicture {
  version: string
  width: number
  height: number
  provider: string
  title: string | null
  artist: string | null
  license: string
  license_url: string | null
  page_url: string | null
  file_page_url: string
  attribution_required: boolean
}

export interface ExpertDetail extends ExpertSummary {
  error: string | null
  updated_at: string
}

export interface CatalogMeta {
  visibility: Visibility
  is_featured: boolean
  catalog_rank: number | null
  blurb: string | null
  category: string | null
  tags: string[]
  published_at: string | null
}

export interface ExpertWithCatalog extends ExpertDetail {
  catalog: CatalogMeta
}

// ── sharing ─────────────────────────────────────────────────────────────────

/** The owner's view of an expert's share link. `token` is null while it is off. */
export interface ShareState {
  enabled: boolean
  token: string | null
  created_at: string | null
  /** People who have opened this link while signed in. Resets with the link. */
  viewer_count: number
  /** Kept sources the owner uploaded — viewers can read passages from them. */
  uploaded_source_count: number
}

/**
 * What anyone holding a live link sees, signed in or not. No slug, no owner, no
 * error: the share page and its link preview render from this alone.
 */
export interface SharedExpert {
  topic: string
  tier: ExpertTier
  readiness: Readiness
  graph_expanded: boolean
  build_active: boolean | null
  persona_name: string | null
  persona_bio: string | null
  key_concepts: string[]
  source_count: number
  chunk_count: number
  node_count: number
  avg_quality: number | null
  source_type_counts: Record<string, number>
  avatar: ExpertAvatar | null
  picture: ExpertPicture | null
  created_at: string
}

export interface ShareAccept {
  slug: string
  access: ExpertAccess
}

export interface BuildRequestBody {
  topic: string
  /** Omitted means "the deepest tier this plan and balance allow". */
  tier?: ExpertTier | null
  sources?: string[] | null
}

// ── billing ─────────────────────────────────────────────────────────────────

export interface Plan {
  name: string
  display_name: string
  included_credits: number
  allowed_tiers: ExpertTier[]
  description: string
}

export interface TierPrice {
  tier: ExpertTier
  credit_cost: number
  spend_cap_usd: number
  included_in_plan: boolean
}

export interface CreditState {
  plan: Plan
  balance: number
  granted: number
  consumed: number
  /** Reserved by a running build, not spent. */
  held: number
  /** When false, every credit element in the UI is hidden. */
  credits_enforced: boolean
  tiers: TierPrice[]
}

export interface LedgerEntry {
  id: number
  entry_type: string
  delta: number
  job_id: number | null
  tier: ExpertTier | null
  reason: string | null
  source: string
  cost_usd: number | null
  created_at: string
}

/**
 * The 402 body. Rendered as a structured panel, never flattened to a toast:
 * the numbers and the single remedy are the whole point of the response.
 */
export interface EntitlementDenial {
  code: 'insufficient_credits' | 'tier_not_in_plan'
  message: string
  tier: ExpertTier
  plan: string
  required_credits?: number
  available_credits?: number
  allowed_tiers?: ExpertTier[]
  remedy: {
    kind: 'request_credits' | 'change_tier' | string
    label: string
    detail: string
  }
}

export function isEntitlementDenial(v: unknown): v is EntitlementDenial {
  if (!v || typeof v !== 'object') return false
  const d = v as Record<string, unknown>
  return (
    (d.code === 'insufficient_credits' || d.code === 'tier_not_in_plan') &&
    typeof d.message === 'string'
  )
}

// ── build job ───────────────────────────────────────────────────────────────

export interface BuildStatus {
  job_id: number
  expert_status: ExpertStatus
  expert_readiness: Readiness
  job_status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  attempts: number
  max_attempts: number
  last_error: string | null
  updated_at: string
}

export interface BuildUsageStage {
  stage: string
  calls: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
}

export interface BuildUsage {
  job_id: number
  expert_id: number
  status: string
  cost_usd: number
  input_tokens: number
  output_tokens: number
  embed_tokens: number
  spend_cap_usd: number | null
  cap_exceeded_at: string | null
  by_stage: BuildUsageStage[]
  by_model: {
    provider: string
    mode: string
    model: string
    calls: number
    cost_usd: number
  }[]
  discovery?: {
    estimated_ingest_usd: number | null
    actual_ingest_usd: number
    estimator_error: number | null
    note: string
    [k: string]: unknown
  }
}

export interface CancelBuildResult {
  job_id: number
  status: 'cancelled'
  credits_refunded: number
}

// ── build events ────────────────────────────────────────────────────────────

/**
 * Every event type the build stream emits, from `experts/builder.py`,
 * `jobs/worker.py` and the `created` event the build route appends.
 *
 * `BuildEvent` is a discriminated union but the reducer must still tolerate an
 * unknown `type`: a newer API may emit an event this build of the web app has
 * never heard of, and the correct response is to ignore it, not to throw.
 */
export type BuildEventType =
  | 'created'
  | 'build_started'
  | 'execution_mode'
  | 'plan_ready'
  | 'discovery_started'
  | 'round_started'
  | 'canonical_resolved'
  | 'primary_texts_suggested'
  | 'fetcher_done'
  | 'fetcher_retried'
  | 'dedup_done'
  | 'floor_relaxed'
  | 'triage_done'
  | 'fetch_progress'
  | 'fetch_done'
  | 'resolve_progress'
  | 'composition_capped'
  | 'validate_done'
  | 'source_validated'
  | 'source_reviewed'
  | 'source_ingested'
  | 'snowball_done'
  | 'feedback_queries'
  | 'coverage_report'
  | 'discovery_done'
  | 'corpus_warning'
  | 'stage'
  | 'chat_ready'
  | 'graph_batch_done'
  | 'entities_resolved'
  | 'claims_reconciled'
  | 'graph_ready'
  | 'persona_ready'
  | 'stage_degraded'
  | 'retry'
  | 'error'
  | 'cancelled'
  | 'done'

export const TERMINAL_BUILD_EVENTS = new Set<string>(['done', 'error', 'cancelled'])

/** Pipeline stage names, in order, as the `stage` event reports them. */
export type StageName =
  'plan' | 'discover' | 'validate' | 'chunk' | 'graph' | 'resolve' | 'reconcile' | 'persona'

interface BuildEventBase {
  type: string
  [k: string]: unknown
}

export interface CreatedEvent extends BuildEventBase {
  type: 'created'
  slug: string
  expert_id: number
  job_id: number
  tier: ExpertTier
  topic: string
}

export interface StageEvent extends BuildEventBase {
  type: 'stage'
  stage: number
  name: StageName
  round?: number
  total?: number
  total_batches?: number
}

export interface SourceValidatedEvent extends BuildEventBase {
  type: 'source_validated'
  round: number
  title: string
  source_type: string
  q: number
  r: number
  passed: boolean
  drop_reason: string | null
}

export interface SourceReviewedEvent extends BuildEventBase {
  type: 'source_reviewed'
  round: number
  title: string
  source_type: string
  first_q: number | null
  first_r: number | null
  q: number
  r: number
  passed: boolean
  reversed: boolean
  review_model: string
}

/** How one search channel ended. `skipped` is a deliberate no-op, not a failure. */
export type FetcherStatus = 'ok' | 'empty' | 'timeout' | 'rate_limited' | 'error' | 'skipped'

export interface FetcherDoneEvent extends BuildEventBase {
  type: 'fetcher_done'
  round: number
  name: string
  count: number
  skipped: boolean
  reason: string | null
  queries: number
  /** Absent from builds before source selection (migration 029). */
  status?: FetcherStatus
  error?: string
  /** 0 on the first try, 1 on the retry after a timeout or a 429. */
  attempt?: number
  /** Seconds. */
  elapsed?: number
}

export interface FetcherRetriedEvent extends BuildEventBase {
  type: 'fetcher_retried'
  round: number
  name: string
  after: 'timeout' | 'rate_limited'
}

/** Too few candidates cleared the fetch floor, so this round fetches lower. */
export interface FloorRelaxedEvent extends BuildEventBase {
  type: 'floor_relaxed'
  round: number
  floor: number
  relaxed_to: number
  reaching: number
  needed: number
}

export interface TriageDoneEvent extends BuildEventBase {
  type: 'triage_done'
  round: number
  candidates: number
  ranked: number
  budget: number
  floor?: number
  above_floor?: number
  /** Candidates the model never scored; they are not fetched. */
  unscored?: number
}

/** What happened to each ranked candidate at fetch time. */
export type FetchOutcome =
  'fetched' | 'failed' | 'capped' | 'below_floor' | 'budget' | 'not_reached' | 'content_duplicate'

export interface FetchDoneEvent extends BuildEventBase {
  type: 'fetch_done'
  round: number
  fetched: number
  content_duplicates: number
  budget: number
  estimated_ingest_usd: number
  /** `not_english`: fetched sources dropped as not in the corpus language. */
  outcomes?: Partial<Record<FetchOutcome | 'not_english' | string, number>>
}

export type MustHaveKind = 'text' | 'book' | 'paper' | 'standard'

/** A work the plan says a corpus on this topic cannot do without. */
export interface MustHaveWork {
  title: string
  author: string
  kind: MustHaveKind
  public_domain: boolean
  sections: string
}

/** Whether a must-have work is canonical for the whole topic or the primary text for a concept. */
export type MustHaveScope = 'overall' | 'concept'

/** The primary text the plan names for one key concept. */
export interface ConceptPrimaryText extends MustHaveWork {
  concept: string
}

export interface CanonicalResolution {
  title: string
  author: string
  kind: MustHaveKind
  public_domain: boolean
  routes_tried: string[]
  route_errors: Record<string, string>
  /** Absent before concept primary texts; treat as `overall`. */
  scope?: MustHaveScope
  concepts?: string[]
  sections?: string
  candidates: {
    url: string
    title: string
    extent: 'whole' | 'partial' | null
    route: string | null
    priority?: boolean
  }[]
}

export interface CanonicalResolvedEvent extends BuildEventBase {
  type: 'canonical_resolved'
  round: number
  works: CanonicalResolution[]
}

/** Primary texts looked up for concepts the corpus still has none for. */
export interface PrimaryTextsSuggestedEvent extends BuildEventBase {
  type: 'primary_texts_suggested'
  round: number
  concepts: string[]
  texts: ConceptPrimaryText[]
}

export interface CompositionCappedEvent extends BuildEventBase {
  type: 'composition_capped'
  round: number
  dropped: { title: string; reason: string }[]
}

export interface ValidateDoneEvent extends BuildEventBase {
  type: 'validate_done'
  round: number
  passed: number
  dropped: number
  capped?: number
}

export interface FeedbackQueriesEvent extends BuildEventBase {
  type: 'feedback_queries'
  round: number
  queries: string[]
  concepts?: string[]
  without_primary?: string[]
  fetchers?: string[]
  retried_fetchers?: string[]
}

export interface ChatReadyEvent extends BuildEventBase {
  type: 'chat_ready'
  sources: number
  chunks: number
  graph_expanded: boolean
}

export interface GraphReadyEvent extends BuildEventBase {
  type: 'graph_ready'
  nodes: number
  edges: number
  graph_expanded: boolean
}

export interface PlanReadyEvent extends BuildEventBase {
  type: 'plan_ready'
  key_concepts: string[]
  /** Absent from builds before source selection. */
  fetcher_plans?: Record<string, { queries: string[]; weight: number }>
  must_have_works?: MustHaveWork[]
  /** Absent before concept primary texts. */
  primary_source_definition?: string
  concept_primary_texts?: ConceptPrimaryText[]
}

export interface SourceIngestedEvent extends BuildEventBase {
  type: 'source_ingested'
  title: string
  chunks: number
  total_chunks: number
}

export interface StageDegradedEvent extends BuildEventBase {
  type: 'stage_degraded'
  stage: string
  message: string
}

export interface DoneEvent extends BuildEventBase {
  type: 'done'
  expert_id?: number
  source_count?: number
  chunk_count?: number
  node_count?: number
  edge_count?: number
  persona_name?: string | null
  avg_quality?: number | null
}

export interface ErrorEvent extends BuildEventBase {
  type: 'error'
  message: string
  /** Only the spend-cap abort sets a code; it is terminal and not retryable. */
  code?: 'spend_cap_exceeded' | string
  spent_usd?: number
  cap_usd?: number
}

export interface RetryEvent extends BuildEventBase {
  type: 'retry'
  attempt: number
  max_attempts: number
  message: string
}

export interface CoverageReportEvent extends BuildEventBase {
  type: 'coverage_report'
  round?: number
}

export interface DiscoveryDoneEvent extends BuildEventBase {
  type: 'discovery_done'
  rounds: number
  stop_reason: string
  corpus?: CorpusComposition
  /** Fetcher name → the status it failed with. */
  failed_channels?: Record<string, FetcherStatus | string>
}

export type BuildEvent =
  | CreatedEvent
  | StageEvent
  | SourceValidatedEvent
  | SourceReviewedEvent
  | FetcherDoneEvent
  | TriageDoneEvent
  | FetchDoneEvent
  | ChatReadyEvent
  | GraphReadyEvent
  | PlanReadyEvent
  | SourceIngestedEvent
  | StageDegradedEvent
  | DoneEvent
  | ErrorEvent
  | RetryEvent
  | CoverageReportEvent
  | FetcherRetriedEvent
  | FloorRelaxedEvent
  | CanonicalResolvedEvent
  | PrimaryTextsSuggestedEvent
  | CompositionCappedEvent
  | ValidateDoneEvent
  | FeedbackQueriesEvent
  | DiscoveryDoneEvent
  | BuildEventBase

// ── conversations ───────────────────────────────────────────────────────────

export interface Citation {
  n: number
  /** The source's title. It used to carry the fetcher and the screening score. */
  label: string
  /**
   * The passage itself, trimmed to ~600 characters by the API.
   *
   * Optional because an answer stored before the field existed has none: the
   * panel falls back to naming the source rather than quoting something that is
   * not a quotation.
   */
  text?: string | null
  source_id: number | null
  /** The chunk the passage is, so the reader can show what surrounds it. */
  chunk_id?: number | null
  /** This passage is on one side of a disagreement in the corpus. */
  disputed?: boolean
  /** What is disputed, in the subject's terms. */
  dispute_points?: string[]
  /** Client-side only: the number this citation shows as within its answer —
   *  1, 2, 3 in order of first use — where `n` is the passage index. */
  display?: number
}

/** One chunk of a source, as the reader shows it. */
export interface Passage {
  chunk_id: number
  sequence_n: number
  section: string | null
  paragraph_n: number | null
  text: string
}

/**
 * A cited passage with what surrounds it — or, where the licence allows, the
 * whole of a source.
 *
 * `scope` is the server's answer, never the client's ask: asking for the whole
 * of a source we may not reproduce returns a window and says so, and
 * `whole_available` is what the "read it all" action is offered on.
 */
export interface PassageWindow {
  source: {
    id: number
    title: string
    author: string | null
    url: string | null
    source_type: string
    full_text_method: string | null
    text_chars: number | null
    passage_count: number
  }
  scope: 'window' | 'whole'
  whole_available: boolean
  cited: number | null
  passages: Passage[]
}

export interface ConversationMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  citations: Citation[] | null
  has_contradiction: boolean
  interrupted: boolean
  created_at: string
}

export interface ConversationSummary {
  id: string
  expert_id: number
  expert_slug: string
  expert_topic: string
  expert_persona_name: string | null
  expert_status: ExpertStatus
  /** The expert's found picture, as a version only — enough to draw the tile.
   *  A chat row has no room for a credit line and shows none, so the rest of
   *  the provenance is deliberately not on every sidebar fetch. */
  expert_picture_version: string | null
  title: string | null
  message_count: number
  created_at: string
  last_message_at: string
}

export interface ConversationDetail extends ConversationSummary {
  messages: ConversationMessage[]
}

// ── chat events ─────────────────────────────────────────────────────────────

export interface ChatMetaEvent {
  type: 'meta'
  conversation_id: string
  title: string | null
}

export interface ChatStatusEvent {
  type: 'status'
  message: string
}

export interface ChatTokenEvent {
  type: 'token'
  text: string
}

export interface ChatSourcesEvent {
  type: 'sources'
  citations: Citation[]
  has_contradiction: boolean
  /** Markers the answer invented; render these as plain text, not links. */
  dangling_citations: number[]
}

export interface RetrievalAuditPassage {
  n: number
  chunk_id: number
  source_id: number
  source_title: string
  source_type: string
  quality_score: number | null
  retrieval_rank: number
  retrieval_score: number
  retrieved_via: string
  disposition: 'cited' | 'considered'
}

export interface ChatRetrievalAuditEvent {
  type: 'retrieval_audit'
  audit_id: string | null
  persisted: boolean
  passages_considered?: number
  passages_in_prompt?: number
  passages_cited?: number
  subqueries?: string[]
  follow_ups?: string[]
  coverage_verdict?: string | null
  graph_expanded?: boolean
  passages?: RetrievalAuditPassage[]
  [k: string]: unknown
}

/**
 * One stored retrieval trail, as `GET /experts/{slug}/answer-audits` returns it.
 *
 * The same facts as the live `retrieval_audit` event under different names —
 * the event is written for a stream and this is written for a record — so the
 * chat page maps one onto the other rather than teaching the card two shapes.
 */
export interface StoredAnswerAudit {
  audit_id: string
  conversation_id: string | null
  question: string
  subqueries: string[]
  followup_queries: string[]
  coverage_satisfied: boolean | null
  second_pass: boolean | null
  passages: {
    retrieved: number
    duplicate_hits: number
    unique: number
    in_context: number
    cited: number
    not_in_context: number
    context_cap: number | null
  }
  sources: { in_context: number; cited: number }
  contradiction_traversed: boolean | null
  answer_chars: number
  created_at: string
}

export interface AnswerAuditsPage {
  audits: StoredAnswerAudit[]
}

export interface ChatDoneEvent {
  type: 'done'
}

export interface ChatErrorEvent {
  type: 'error'
  message: string
}

export type ChatEvent =
  | ChatMetaEvent
  | ChatStatusEvent
  | ChatTokenEvent
  | ChatSourcesEvent
  | ChatRetrievalAuditEvent
  | ChatDoneEvent
  | ChatErrorEvent
  | { type: string; [k: string]: unknown }

// ── corpus report (the ledger) ──────────────────────────────────────────────

export interface LedgerSource {
  id: number
  decision: 'accepted' | 'rejected'
  title: string
  url: string | null
  author: string | null
  source_type: string
  content_type: string | null
  difficulty: number | null
  quality_score: number | null
  relevance_score: number | null
  /** Always null on accepted rows. */
  drop_reason: string | null
  source_tier: string | null
  doi: string | null
  arxiv_id: string | null
  identifiers: Record<string, string> | null
  /** How much of the source was actually read: `abstract` means the abstract. */
  full_text_method: string | null
  text_chars: number | null
  validator_model: string | null
  review_model: string | null
  first_pass_quality: number | null
  first_pass_relevance: number | null
  reviewed: boolean
  rubric_version: string | null
  discovered_via: string | null
  /** Parsed from `discovered_via` server-side; prefer it to string-splitting. */
  discovery_method: string | null
  gap_filled_for_concept: string | null
  snowball_seed_urls: string[] | null
  covered_concepts: string[]
  key_claims: string[]
  passage_count: number
  created_at: string
}

export interface AuditPage {
  decision?: SourceDecision
  sort?: SourceSort
  limit: number
  offset: number
  returned: number
  total_matching: number | null
  has_more: boolean
}

export interface CorpusReport {
  expert: { name: string; topic: string; tier: ExpertTier; [k: string]: unknown }
  method_statement: string
  totals: {
    considered: number
    accepted: number
    rejected: number
    acceptance_rate: number | null
    accepted_with_passages: number
    accepted_without_passages: number
    passages_total: number
  }
  scores: {
    accepted: Record<string, number | null>
    rejected: Record<string, number | null>
    distribution?: Record<string, Record<string, number[]>>
    bin_edges?: number[][]
  }
  thresholds: {
    quality_min: number
    relevance_min: number
    current_rubric_version: string
    note: string
  }
  rubric_versions: {
    rubric_version: string | null
    validator_model: string | null
    sources: number
    accepted: number
    first_seen: string | null
    last_seen: string | null
  }[]
  provenance: {
    sources: number
    complete: boolean
    missing: Record<string, number>
    note: string
  }
  by_source_type: {
    source_type: string
    considered: number
    accepted: number
    rejected: number
    accepted_mean_quality: number | null
    accepted_mean_relevance: number | null
  }[]
  by_discovery_method: {
    method: string
    considered: number
    accepted: number
    rejected: number
    accepted_mean_quality: number | null
  }[]
  by_search: {
    searches: {
      discovered_via: string
      method: string
      concept: string | null
      considered: number
      accepted: number
      rejected: number
      accepted_mean_quality: number | null
      accepted_mean_relevance: number | null
      source_types: string[]
    }[]
    distinct_searches: number
    note: string
  }
  exclusions: {
    by_reason: {
      reason: string
      count: number
      mean_quality: number | null
      mean_relevance: number | null
    }[]
    by_threshold: Record<string, number>
    by_threshold_meanings: Record<string, string>
  }
  page: AuditPage
  sources: LedgerSource[]
}

// ── source selection (the screening-flow report) ────────────────────────────

/**
 * `found_sections`: the named sections of a long work were found and kept —
 * as good as whole for a work the plan only needs part of.
 */
export type MustHaveStatus = 'found_whole' | 'found_sections' | 'found_partial' | 'not_found'

/**
 * What the corpus is made of, computed once at the end of discovery and stored
 * in `build_summary.corpus`. Shares are 0..1 over `sources`.
 */
export interface CorpusComposition {
  sources: number
  primary: number
  secondary: number
  tertiary: number
  unclassified: number
  abstract_only: number
  primary_share: number
  secondary_share: number
  tertiary_share: number
  abstract_only_share: number
  /** Fetched sources the validator scored 3 or less for relevance. */
  junk_fetched: number
  concept_shares: Record<string, number>
  concepts_without_primary: string[]
  must_have: {
    title: string
    author: string
    status: MustHaveStatus
    source_urls: string[]
    routes_tried: string[]
    route_errors: Record<string, string>
    /** The four below are absent from older builds; no scope means `overall`. */
    kind?: MustHaveKind
    scope?: MustHaveScope
    concepts?: string[]
    sections?: string
  }[]
}

export interface CandidateLedgerRow {
  round: number
  /** Null when triage saw the candidate but the fetch stage never recorded it. */
  fetch_outcome: FetchOutcome | string | null
  triage_status: string
  count: number
  mean_triage_score: number | null
}

export type SelectionBlock =
  | { available: false; unavailable_reason: string }
  | {
      available: true
      corpus: CorpusComposition | null
      failed_channels: Record<string, FetcherStatus | string>
      candidate_ledger: { job_id: number | null; rows: CandidateLedgerRow[] } | null
      note: string
    }

/**
 * `GET /experts/{slug}/screening-flow`. Only the part the web renders is typed
 * here; the funnel stages, discovery and gap-fill blocks ride along untyped.
 */
export interface ScreeningFlow {
  expert: { name: string; topic: string; [k: string]: unknown }
  method_statement: string
  /** Absent from servers older than source selection. */
  selection?: SelectionBlock
  [k: string]: unknown
}

// ── sources (owner-scoped management view) ──────────────────────────────────

export interface SourceRow {
  id: number
  source_type: string
  url: string | null
  title: string
  author: string | null
  quality_score: number | null
  content_type: string | null
  discovered_via: string | null
  source_tier: string | null
  chunk_count: number
  created_at: string
}

export interface UploadAccepted {
  upload_id: number
  /** The job to tail on `…/build/events` — ingest rides the build stream. */
  job_id: number
  title: string
  kind: 'pdf' | 'text' | 'url' | string
}

// ── graph ───────────────────────────────────────────────────────────────────

export interface GraphNode {
  id: number
  label: string
  node_type: string
  degree: number
}

export interface GraphEdge {
  id: number
  source: number
  target: number
  edge_type: string
  evidence: number
}

export interface GraphResponse {
  expert: { name: string; topic: string; [k: string]: unknown }
  /** False while the concept graph is still being extracted. Never render an
   *  empty canvas in that state — say the graph is still building. */
  computed: boolean
  nodes: GraphNode[]
  edges: GraphEdge[]
  total_nodes: number
  total_edges: number
  truncated: boolean
}

// ── misc ────────────────────────────────────────────────────────────────────

export interface GrantCreditsBody {
  owner: string
  amount: number
  reason?: string | null
  plan?: string | null
}

export interface GrantCreditsResult {
  owner_id: string
  balance: number
  granted: number
}
