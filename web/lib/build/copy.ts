import type { ExpertTier } from '@/lib/api/types'

/**
 * What each depth means to the person choosing it, and the one-line form the
 * Overview prints beside it.
 *
 * Only what is actually fixed per tier (`ExpertConfig` in the API): how many
 * discovery rounds run and how many passages an answer may cite. The absolute
 * source count depends on the topic's plan, so it is never promised — which is
 * why "Standard" alone said nothing to someone who let *Auto* choose, and why
 * the hint talks about rounds rather than sources.
 */
export const DEPTH: Record<ExpertTier, { label: string; blurb: string; hint: string }> = {
  lite: {
    label: 'Lite',
    blurb: 'Quickest. About half the sources of Standard; answers cite up to 8 passages.',
    hint: 'one round of searching · answers cite up to 8 passages',
  },
  standard: {
    label: 'Standard',
    blurb: 'Balanced. Two rounds of searching; answers cite up to 15 passages.',
    hint: 'two rounds of searching · answers cite up to 15 passages',
  },
  pro: {
    label: 'Pro',
    blurb: 'Deepest and slowest. About twice the sources, three rounds; answers cite up to 25.',
    hint: 'three rounds of searching · answers cite up to 25 passages',
  },
}

/** The depth hint, or an empty string for a tier this build predates. */
export function depthHint(tier: string | null | undefined): string {
  return (tier && DEPTH[tier as ExpertTier]?.hint) || ''
}

/**
 * A build failure, in words for the person who asked for the build.
 *
 * The API's messages are written for a log ("Build finished without: key
 * concepts (research planning failed). An expert is only ready once…"). Those
 * stay available as the detail; this is the sentence a reader acts on.
 */
export function describeBuildFailure(raw: string | null | undefined): {
  headline: string
  advice: string
} {
  const message = (raw ?? '').toLowerCase()

  if (message.includes('research planning failed') || message.includes('key concepts')) {
    return {
      headline: 'Planning the search failed, so nothing was searched.',
      advice: 'Rebuilding usually fixes this.',
    }
  }
  if (message.includes('failed validation') || message.includes('no sources passed')) {
    return {
      headline: 'None of the sources found were good enough to keep.',
      advice: 'Try a more specific topic, or rebuild at a deeper tier.',
    }
  }
  if (message.includes('spend cap')) {
    return {
      headline: 'The build stopped at its spend cap.',
      advice: 'Your credits were refunded. Rebuild at a different depth or narrow the topic.',
    }
  }
  if (message.includes('cancel')) {
    return { headline: 'The build was cancelled.', advice: 'Start it again from Settings.' }
  }
  if (message.includes('credit')) {
    return {
      headline: 'There were not enough credits to run this build.',
      advice: 'Request credits, then rebuild.',
    }
  }
  if (message.includes('anthropic') || message.includes('provider')) {
    return {
      headline: 'The AI provider refused the request, so the build could not continue.',
      advice: 'Nothing was charged. Try again later.',
    }
  }
  return {
    headline: 'The build stopped before this expert could answer.',
    advice: 'Rebuilding usually fixes this.',
  }
}
