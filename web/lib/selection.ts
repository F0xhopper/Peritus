/**
 * Phrasings for the search channels a build runs. Pure, so the wording is
 * unit-tested rather than trusted to a component.
 */
const CHANNEL_STATUS: Record<string, string> = {
  timeout: 'timed out',
  rate_limited: 'rate-limited',
  error: 'failed',
  empty: 'found nothing',
  skipped: 'skipped',
}

/** A fetcher status as the build log phrases it. */
export function describeChannelStatus(status: string): string {
  return CHANNEL_STATUS[status] ?? status.replace(/_/g, ' ')
}
