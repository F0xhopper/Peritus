import { describe, expect, it } from 'vitest'

import schema from '../../api/openapi.json'
import type { components } from '@/lib/api/types.generated'
import type {
  Citation,
  ConversationDetail,
  ConversationSummary,
  ExpertSummary,
  ExpertWithCatalog,
  LedgerEntry,
  Me,
  ShareAccept,
  ShareState,
  SharedExpert,
  SourceRow,
} from '@/lib/api/types'

/**
 * The link between the Python schemas and the TypeScript that reads them.
 *
 * `lib/api/types.ts` is hand-written, deliberately: it carries the prose that
 * explains *why* a count may be null, and it narrows where the schema cannot —
 * a Pydantic `str` that is documented as one of four values is a union here,
 * and giving that up would be a real loss.
 *
 * What it could not do on its own is notice a rename on the other side. A field
 * dropped from a response model simply became `undefined` in someone's browser,
 * and the fixture tests only cover payloads that happened to be captured.
 *
 * So the check is on **field names**, not on full types: exactly the thing a
 * rename changes, and the one thing narrowing does not touch. `api/openapi.json`
 * comes from the FastAPI app and `types.generated.ts` from that (`just types`);
 * CI regenerates both and fails on a diff, so they cannot be stale.
 *
 * A failure here reads as "Type 'false' is not assignable to type 'true'" at the
 * offending line — go to the pair named on that line and compare the fields.
 */

type Schemas = components['schemas']

/** Fails to compile unless `T` is exactly `true`. */
type Assert<T extends true> = T

/** The keys the API sends that the hand-written type has no name for. */
type Unknown_<Wire, Ours> = Exclude<keyof Wire, keyof Ours>

/** The keys the hand-written type expects that the API no longer sends. */
type Missing<Wire, Ours> = Exclude<keyof Ours, keyof Wire>

/** Both directions, for one pair. */
type Matches<Wire, Ours> =
  Unknown_<Wire, Ours> extends never ? (Missing<Wire, Ours> extends never ? true : false) : false

// ── experts ──
type _Expert = Assert<Matches<Schemas['ExpertSummary'], ExpertSummary>>
type _ExpertWithCatalog = Assert<Matches<Schemas['ExpertWithCatalog'], ExpertWithCatalog>>

// ── conversations ──
type _ConversationSummary = Assert<Matches<Schemas['ConversationSummary'], ConversationSummary>>
type _ConversationDetail = Assert<Matches<Schemas['ConversationDetail'], ConversationDetail>>
// `display` is the client's own per-answer number and has no wire counterpart,
// so it is excluded from our side rather than added to the schema.
type _Citation = Assert<Matches<Schemas['Citation'], Omit<Citation, 'display'>>>

// ── sources, sharing, billing, identity ──
type _Source = Assert<Matches<Schemas['SourceOut'], SourceRow>>
type _ShareState = Assert<Matches<Schemas['ShareStateOut'], ShareState>>
type _ShareAccept = Assert<Matches<Schemas['ShareAcceptOut'], ShareAccept>>
type _SharedExpert = Assert<Matches<Schemas['SharedExpertOut'], SharedExpert>>
type _Ledger = Assert<Matches<Schemas['LedgerEntryOut'], LedgerEntry>>
type _Me = Assert<Matches<Schemas['MeResponse'], Me>>

describe('the committed schema is the one this app was built against', () => {
  it('carries every route the web client has a handler for', () => {
    // A runtime check beside the compile-time ones: a stale `openapi.json`
    // would make every assertion above pass against yesterday's API.
    const paths = Object.keys((schema as { paths: Record<string, unknown> }).paths)
    for (const path of [
      '/experts',
      '/experts/build',
      '/experts/{slug}',
      '/experts/{slug}/chat',
      '/experts/{slug}/conversations',
      '/experts/{slug}/share',
      '/experts/{slug}/sources',
      '/conversations/{conversation_id}/messages',
      '/share/{token}',
      '/billing/me',
      '/auth/otp',
      '/auth/verify',
    ]) {
      expect(paths).toContain(path)
    }
  })
})
