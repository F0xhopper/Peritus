import { describe, expect, it } from 'vitest'

import billing from './fixtures/billing.json' with { type: 'json' }
import chatEvents from './fixtures/chat-events.json' with { type: 'json' }
import corpusReport from './fixtures/corpus-report.json' with { type: 'json' }
import denials from './fixtures/denial.json' with { type: 'json' }
import expert from './fixtures/expert.json' with { type: 'json' }
import expertMap from './fixtures/map.json' with { type: 'json' }
import mapConcept from './fixtures/map-concept.json' with { type: 'json' }
import mapPending from './fixtures/map-not-computed.json' with { type: 'json' }
import screeningFlow from './fixtures/screening-flow.json' with { type: 'json' }
import {
  isEntitlementDenial,
  type ChatEvent,
  type CorpusReport,
  type CreditState,
  type EntitlementDenial,
  type ExpertWithCatalog,
  type MapConceptDetail,
  type MapResponse,
  type ScreeningFlow,
} from '@/lib/api/types'

/**
 * Schema drift detection.
 *
 * The point of this file is the **type annotations**, not the assertions. There
 * is no codegen between `api/src/peritus/api/schemas/*.py` and
 * `lib/api/types.ts`, so a field the API renames or a type it changes would
 * otherwise surface as `undefined` in a user's browser. Binding each captured
 * payload to its interface turns that into a `tsc` failure on the next build.
 *
 * The assertions cover the handful of contract rules the types cannot express:
 * null means "not recorded", `drop_reason` is null on accepted rows, and
 * `computed: false` comes with an empty cloud.
 */

// These four annotations are the actual test.
const expertFixture: ExpertWithCatalog = expert as ExpertWithCatalog
const billingFixture: CreditState = billing as CreditState
const reportFixture: CorpusReport = corpusReport as CorpusReport
const mapFixture: MapResponse = expertMap as MapResponse
const mapPendingFixture: MapResponse = mapPending as MapResponse
const mapConceptFixture: MapConceptDetail = mapConcept as MapConceptDetail
const chatFixtures: Record<string, ChatEvent> = chatEvents
const flowFixture: ScreeningFlow = screeningFlow as ScreeningFlow

describe('expert detail', () => {
  it('carries the readiness field chat is gated on', () => {
    expect(expertFixture.readiness).toBe('graph_ready')
    // `status` is never what the chat affordance reads.
    expect(expertFixture.status).toBe('ready')
  })

  it('carries a null avatar, meaning "derive it"', () => {
    // Present and null, never absent — the client branches on it.
    expect('avatar' in expertFixture).toBe(true)
    expect(expertFixture.avatar).toBeNull()
  })

  it('carries a found picture with the provenance its licence obliges', () => {
    // `attribution_required` is the field that decides whether a credit line
    // renders, so its companions have to be there whenever it is true.
    expect(expertFixture.picture).not.toBeNull()
    expect(expertFixture.picture?.attribution_required).toBe(true)
    expect(expertFixture.picture?.artist).toBeTruthy()
    expect(expertFixture.picture?.file_page_url).toMatch(/^https:\/\//)
    // The version is what makes the image URL safe to cache immutably.
    expect(expertFixture.picture?.version).toMatch(/^[0-9a-f]{12}$/)
  })

  it('carries the catalog block on an owner-facing response', () => {
    expect(expertFixture.catalog.visibility).toBe('private')
  })

  it('says whether the caller owns it, which decides every management control', () => {
    expect(expertFixture.access).toBe('owner')
  })
})

describe('billing', () => {
  it('lists a price for every tier, including ones off the plan', () => {
    expect(billingFixture.tiers.map((tier) => tier.tier)).toEqual(['lite', 'standard', 'pro'])
    const pro = billingFixture.tiers.find((tier) => tier.tier === 'pro')!
    // A tier outside the plan still has a price, so the picker can show it
    // disabled *with its cost* rather than as a blank.
    expect(pro.included_in_plan).toBe(false)
    expect(pro.credit_cost).toBeGreaterThan(0)
  })

  it('reports enforcement separately from the balance', () => {
    expect(billingFixture.credits_enforced).toBe(true)
  })
})

describe('entitlement denials', () => {
  it('are both recognised by the guard', () => {
    for (const denial of Object.values(denials)) {
      expect(isEntitlementDenial(denial)).toBe(true)
    }
  })

  it('always carry exactly one remedy', () => {
    for (const denial of Object.values(denials) as EntitlementDenial[]) {
      expect(denial.remedy.label).toBeTruthy()
      expect(denial.remedy.detail).toBeTruthy()
    }
  })

  it('quote the numbers on an insufficient-credits denial', () => {
    const denial = denials.insufficient_credits as EntitlementDenial
    expect(denial.required_credits).toBe(8)
    expect(denial.available_credits).toBe(2)
    // There is no checkout, so the remedy is always to ask.
    expect(denial.remedy.kind).toBe('request_credits')
  })

  it('name the allowed tiers on a plan denial', () => {
    const denial = denials.tier_not_in_plan as EntitlementDenial
    expect(denial.allowed_tiers).toEqual(['lite', 'standard'])
    expect(denial.remedy.kind).toBe('change_tier')
  })

  it('rejects things that merely look like denials', () => {
    expect(isEntitlementDenial({ code: 'something_else', message: 'x' })).toBe(false)
    expect(isEntitlementDenial('insufficient_credits')).toBe(false)
    expect(isEntitlementDenial(null)).toBe(false)
  })
})

describe('corpus report', () => {
  it('holds both halves of the ledger', () => {
    const decisions = new Set(reportFixture.sources.map((source) => source.decision))
    // The rejected half is a first-class view, not a debug panel.
    expect(decisions).toEqual(new Set(['accepted', 'rejected']))
  })

  it('leaves drop_reason null on accepted rows and set on rejected ones', () => {
    for (const source of reportFixture.sources) {
      if (source.decision === 'accepted') expect(source.drop_reason).toBeNull()
      else expect(source.drop_reason).toBeTruthy()
    }
  })

  it('computes totals over the whole corpus, not the returned page', () => {
    expect(reportFixture.page.returned).toBe(3)
    expect(reportFixture.totals.considered).toBe(30)
    expect(reportFixture.page.total_matching).toBe(30)
  })

  it('marks an abstract-only source, which is what a reviewer asks first', () => {
    const abstractOnly = reportFixture.sources.find(
      (source) => source.full_text_method === 'abstract'
    )
    expect(abstractOnly).toBeDefined()
  })

  it('records a reviewed row with both verdicts', () => {
    const reviewed = reportFixture.sources.find((source) => source.reviewed)!
    expect(reviewed.first_pass_quality).toBe(5.5)
    expect(reviewed.quality_score).toBe(8.0)
    // The second verdict is the one that stands.
    expect(reviewed.review_model).toBeTruthy()
  })

  it('carries a gapfill row with the concept that caused the search', () => {
    const gapfill = reportFixture.sources.find((source) => source.discovery_method === 'gapfill')!
    expect(gapfill.gap_filled_for_concept).toBe('acaricide resistance')
  })

  it('records a duplicate as a rejection with a stated reason, scored zero', () => {
    const duplicate = reportFixture.exclusions.by_reason.find((reason) =>
      reason.reason.startsWith('duplicate of')
    )!
    // Zeros here are not a quality verdict — it was never judged on merit.
    expect(duplicate.mean_quality).toBe(0)
  })

  it('carries a method statement to render beside the data', () => {
    expect(reportFixture.method_statement.length).toBeGreaterThan(40)
  })
})

describe('screening flow', () => {
  it('carries an available selection block with the composition and the ledger', () => {
    const selection = flowFixture.selection!
    expect(selection.available).toBe(true)
    if (!selection.available) return
    expect(selection.corpus?.primary_share).toBeGreaterThan(0)
    expect(selection.corpus?.must_have.map((work) => work.status)).toEqual([
      'found_whole',
      'found_partial',
      'not_found',
      'found_sections',
      'not_found',
    ])
    expect(selection.candidate_ledger?.rows.length).toBeGreaterThan(0)
  })
})

describe('the expert map', () => {
  it('links only concepts it returns, and draws only concepts some kept source discusses', () => {
    const ids = new Set(mapFixture.concepts.map((concept) => concept.id))
    for (const link of mapFixture.links) {
      expect(ids.has(link.from), `link from ${link.from}`).toBe(true)
      expect(ids.has(link.to), `link to ${link.to}`).toBe(true)
    }
    const sources = new Set(mapFixture.sources.map((source) => source.id))
    for (const concept of mapFixture.concepts) {
      expect(concept.source_ids.length).toBeGreaterThan(0)
      for (const id of concept.source_ids) expect(sources.has(id), `source ${id}`).toBe(true)
    }
  })

  it('indexes key concepts from tags, facets, concepts and gaps within the syllabus', () => {
    const count = mapFixture.syllabus.key_concepts.length
    const inRange = (index: number | null) => index === null || (index >= 0 && index < count)
    for (const source of mapFixture.sources)
      for (const tag of source.tags) expect(inRange(tag.key_concept)).toBe(true)
    for (const facet of mapFixture.syllabus.facets ?? [])
      for (const i of facet.concepts) expect(inRange(i)).toBe(true)
    for (const concept of mapFixture.concepts) expect(inRange(concept.key_concept)).toBe(true)
    for (const gap of mapFixture.syllabus.gaps) expect(inRange(gap.key_concept)).toBe(true)
  })

  it('reports what is shown against what exists', () => {
    expect(mapFixture.totals.concepts_shown).toBe(mapFixture.concepts.length)
    expect(mapFixture.totals.concepts).toBeGreaterThan(mapFixture.concepts.length)
  })

  it('pairs computed:false with an empty cloud and unrecorded totals, never zeros', () => {
    expect(mapPendingFixture.computed).toBe(false)
    expect(mapPendingFixture.concepts).toEqual([])
    expect(mapPendingFixture.links).toEqual([])
    // "No concepts found" would be the worst available lie.
    expect(mapPendingFixture.totals.concepts).toBeNull()
    expect(mapPendingFixture.totals.claims).toBeNull()
  })

  it("lists a concept's disputed claims first, each with the point in dispute", () => {
    const [first] = mapConceptFixture.claims
    expect(first.disputed).toBe(true)
    const dispute = first.relations.find((relation) => relation.type === 'contradicts')
    expect(dispute?.point).toBeTruthy()
    for (const claim of mapConceptFixture.claims) {
      for (const source of claim.sources) expect(source.chunk_id).toBeGreaterThan(0)
    }
  })
})

describe('chat events', () => {
  it('covers every type the stream emits', () => {
    const types = new Set(Object.values(chatFixtures).map((event) => event.type))
    expect(types).toEqual(
      new Set(['meta', 'status', 'token', 'sources', 'retrieval_audit', 'done', 'error'])
    )
  })

  it('numbers citations to match the inline markers', () => {
    const sources = chatFixtures.sources as {
      citations: { n: number; label: string; source_id: number | null }[]
      dangling_citations: number[]
    }
    expect(sources.citations.map((citation) => citation.n)).toEqual([1, 3])
    // A marker the answer invented is reported so it can be rendered as text.
    expect(sources.dangling_citations).toEqual([7])
  })

  it('reports the retrieval trail as counts, never as a score', () => {
    const audit = chatFixtures.retrieval_audit as Record<string, unknown>
    expect(audit.passages_considered).toBe(23)
    expect(audit.passages_cited).toBe(2)
    // Explicitly absent: there is no calibration set behind such a number, so
    // displaying one would be a fabrication.
    expect(audit).not.toHaveProperty('faithfulness')
    expect(audit).not.toHaveProperty('grounding_score')
    expect(audit).not.toHaveProperty('confidence')
  })

  it('gives each audited passage a disposition', () => {
    const audit = chatFixtures.retrieval_audit as {
      passages: { disposition: string }[]
    }
    for (const passage of audit.passages) {
      expect(['cited', 'considered']).toContain(passage.disposition)
    }
  })
})
