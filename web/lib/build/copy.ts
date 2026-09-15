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
