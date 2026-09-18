import { PICTURE_SLUG, fixture, pictureMeta, state } from './state.mjs'
import { startBuild } from './streams.mjs'

/**
 * The world every test starts from, rebuilt by `POST /__reset`.
 *
 * Every spec resets first, because the alternative — tests inheriting each
 * other's experts — produces failures that depend on the order Playwright
 * happened to shard them in, which is the worst kind to debug.
 *
 * The seeded set is chosen to cover the states a page must render differently:
 * one ready expert with a picture and a corpus, one mid-build, one failed, and
 * one belonging to *somebody else*, reachable only through its share token.
 */

/** The live link to the seeded foreign expert. 32+ URL-safe characters, like a real token. */
export const FOREIGN_TOKEN = 'mockSharedTokenForTheThomismExpert01'
export const FOREIGN_SLUG = 'thomism'

export async function seed() {
  const expert = await fixture('expert')
  // Deliberately picture-less: this is the expert most specs act on, and its
  // monogram is what the derived-identity assertions are about. The one with a
  // found picture is seeded below, so both branches of the avatar resolver are
  // on screen in every run.
  expert.picture = null
  state.experts.set(expert.name, expert)

  // A second expert that is mid-build, so the rail's pulse, the Building-now
  // card and the pending-readiness chat gate all have something to render.
  state.experts.set('measurement-error-in-nutritional-epidemiology', {
    ...expert,
    id: 42,
    name: 'measurement-error-in-nutritional-epidemiology',
    topic: 'Measurement error in nutritional epidemiology',
    status: 'building',
    readiness: 'pending',
    graph_expanded: false,
    persona_name: null,
    persona_bio: null,
    persona_style: null,
    avg_quality: null,
    source_count: 0,
    chunk_count: 0,
    node_count: 0,
    edge_count: 0,
    source_type_counts: {},
    avatar: null,
    picture: null,
  })

  // A third expert that arrived with a found picture of its subject — the
  // default a freshly built expert now has. Separate from the two above so the
  // monogram assertions stay about the monogram and this one stays about the
  // picture, in the same run.
  state.experts.set(PICTURE_SLUG, {
    ...expert,
    id: 43,
    name: PICTURE_SLUG,
    topic: 'Stoic philosophy',
    persona_name: 'Dr. Aurelia Vance',
    persona_bio: 'A historian of Hellenistic philosophy who reads the Stoics in Greek.',
    persona_style: 'plain, quotes the sources, refuses the self-help reading',
    avatar: null,
    picture: pictureMeta(),
  })

  // A real expert with status 'building' always has a build job behind it, so
  // the seeded one gets a registered (un-streamed) build. Without it the
  // Overview would offer "start a build" for something already building.
  await startBuild('measurement-error-in-nutritional-epidemiology', 'Measurement error')

  const conversation = {
    id: '2f2b8a4e-1c9d-4f8a-9b1e-7c0d2a5f6e31',
    expert_id: expert.id,
    expert_slug: expert.name,
    expert_topic: expert.topic,
    expert_persona_name: expert.persona_name,
    expert_status: expert.status,
    expert_picture_version: null,
    title: 'How effective is drone brood removal on its own?',
    message_count: 2,
    created_at: '2026-09-09T09:00:00.000Z',
    last_message_at: '2026-09-09T09:01:12.000Z',
    messages: [
      {
        id: 1,
        role: 'user',
        content: 'How effective is drone brood removal on its own?',
        citations: null,
        has_contradiction: false,
        interrupted: false,
        created_at: '2026-09-09T09:00:00.000Z',
      },
      {
        id: 2,
        role: 'assistant',
        content:
          'Drone brood removal reduces mite load substantially on its own, but the evidence does not support it as a sole control in high-pressure years [1].\n\nA randomised trial measured a 43% reduction relative to untreated controls over one season [1]. A five-year cohort found that mechanical control alone did not prevent viral amplification when mite pressure was high [3].',
        // The label is the source's title; `text` is the passage itself, which
        // is what the panel quotes.
        citations: [
          {
            n: 1,
            label: 'Drone brood removal as mechanical control: a randomised trial',
            text: 'Removal reduced mite load by 43% relative to untreated controls over one season, with no effect on colony weight at the end of the season.',
            source_id: 812,
            chunk_id: 9001,
            disputed: true,
            dispute_points: [
              'Whether mechanical control alone holds mite load below the treatment threshold in high-pressure years.',
            ],
          },
          {
            n: 3,
            label: 'Varroa destructor and honeybee viral loads: a five-year cohort',
            text: 'Mechanical control alone did not prevent viral amplification in high-pressure years; DWV titres rose in five of the eight study apiaries.',
            source_id: 804,
            chunk_id: 8804,
            disputed: true,
            dispute_points: [
              'Whether mechanical control alone holds mite load below the treatment threshold in high-pressure years.',
            ],
          },
        ],
        has_contradiction: true,
        interrupted: false,
        created_at: '2026-09-09T09:01:12.000Z',
      },
    ],
  }
  state.conversations.set(conversation.id, conversation)

  // Someone else's expert with a live share link. Not in the workspace until the
  // test opens the link, exactly like the real read rule.
  state.foreign = {
    ...expert,
    id: 77,
    name: FOREIGN_SLUG,
    topic: 'Thomism',
    persona_name: 'Fr. Reginald Hale',
    persona_bio: 'A Dominican who reads the Summa slowly and argues with its commentators.',
    persona_style: 'patient, cites article and objection, distinguishes before answering',
    avatar: null,
    picture: pictureMeta(),
    access: 'viewer',
  }
  state.links.set('__foreign__', { token: FOREIGN_TOKEN, viewers: 0 })
}

export function newToken() {
  return Array.from(
    { length: 32 },
    () =>
      'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-'[
        Math.floor(Math.random() * 64)
      ]
  ).join('')
}

export function shareState(slug) {
  const link = state.links.get(slug)
  return {
    enabled: Boolean(link),
    token: link?.token ?? null,
    created_at: link ? '2026-09-15T10:00:00.000Z' : null,
    viewer_count: link?.viewers ?? 0,
    // The seeded expert has one upload, so the dialog's warning has something to say.
    uploaded_source_count: slug === 'varroa-mite-control-in-temperate-beekeeping' ? 1 : 0,
  }
}

/** The anonymous card: no slug, no id, no owner, no error. */
export function sharedCard(expert) {
  const {
    id: _id,
    name: _name,
    status: _status,
    error: _error,
    updated_at: _updated,
    catalog: _catalog,
    access: _access,
    persona_style: _style,
    edge_count: _edges,
    ...card
  } = expert
  return card
}
