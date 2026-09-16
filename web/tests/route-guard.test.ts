import { describe, expect, it } from 'vitest'

import { guardOrigin, pickParams, query } from '@/lib/api/route'

/**
 * The CSRF guard on the mutating route handlers.
 *
 * `SameSite=Lax` already stops a cross-site POST from carrying the session
 * cookie, but it is one mechanism with a history of edge cases in shipped
 * browsers, and `Sec-Fetch-Site` costs nothing to check. Both are in place, so
 * both are tested — and the "no headers at all" case matters, because that is
 * curl and server-to-server, which must keep working.
 */

function request(
  method: string,
  headers: Record<string, string> = {},
  url = 'http://localhost:3000/api/experts/build'
) {
  return new Request(url, { method, headers })
}

describe('guardOrigin', () => {
  it('lets every safe method through untouched', () => {
    for (const method of ['GET', 'HEAD', 'OPTIONS']) {
      expect(guardOrigin(request(method, { origin: 'https://evil.example' }))).toBeNull()
    }
  })

  it('allows a same-origin fetch from the app', () => {
    expect(guardOrigin(request('POST', { 'sec-fetch-site': 'same-origin' }))).toBeNull()
  })

  it('allows sec-fetch-site: none, which cannot be a POST from a page', () => {
    // A typed URL or a bookmark. Not reachable as a cross-site form post.
    expect(guardOrigin(request('POST', { 'sec-fetch-site': 'none' }))).toBeNull()
  })

  it('refuses a cross-site request with 403', () => {
    for (const site of ['cross-site', 'same-site']) {
      const response = guardOrigin(request('POST', { 'sec-fetch-site': site }))
      expect(response?.status, site).toBe(403)
    }
  })

  it('refuses a foreign Origin when Sec-Fetch-Site is absent', () => {
    const response = guardOrigin(request('POST', { origin: 'https://evil.example' }))
    expect(response?.status).toBe(403)
  })

  it('allows a matching Origin when Sec-Fetch-Site is absent', () => {
    expect(guardOrigin(request('POST', { origin: 'http://localhost:3000' }))).toBeNull()
  })

  it('allows a request with neither header — curl and server to server', () => {
    // Those already hold the session cookie, so they are same-origin by
    // construction; refusing them would break the mock API in CI.
    expect(guardOrigin(request('POST'))).toBeNull()
  })

  it('guards DELETE, PATCH and PUT as well as POST', () => {
    for (const method of ['DELETE', 'PATCH', 'PUT']) {
      expect(guardOrigin(request(method, { 'sec-fetch-site': 'cross-site' }))?.status, method).toBe(
        403
      )
    }
  })
})

describe('pickParams', () => {
  it('forwards only the named parameters', () => {
    const params = pickParams(
      'http://localhost:3000/api/experts/x/sources?decision=rejected&sort=quality&evil=1',
      ['decision', 'sort']
    )
    expect(params.get('decision')).toBe('rejected')
    expect(params.get('sort')).toBe('quality')
    // Anything the handler did not name never reaches the API.
    expect(params.has('evil')).toBe(false)
  })

  it('drops empty values rather than forwarding a blank', () => {
    const params = pickParams('http://x/y?after=&limit=5', ['after', 'limit'])
    expect(params.has('after')).toBe(false)
    expect(params.get('limit')).toBe('5')
  })
})

describe('query', () => {
  it('prefixes with ? only when there is something to send', () => {
    expect(query(new URLSearchParams())).toBe('')
    expect(query(new URLSearchParams({ a: '1' }))).toBe('?a=1')
  })
})
