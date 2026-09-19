import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  peekPendingQuestion,
  stashPendingQuestion,
  takePendingQuestion,
} from '@/hooks/use-chat-stream'

// The question carried from the Overview to a new chat. Peeking is what lets
// the loading screen and the chat's first frame show it; taking is what sends
// it, exactly once.
describe('the carried question', () => {
  beforeEach(() => {
    const store = new Map<string, string>()
    globalThis.sessionStorage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    } as unknown as Storage
  })
  afterEach(() => {
    delete (globalThis as { sessionStorage?: Storage }).sessionStorage
  })

  it('can be read any number of times before it is taken, and not after', () => {
    stashPendingQuestion('c1', 'What happens at death?')
    expect(peekPendingQuestion()).toBe('What happens at death?')
    expect(peekPendingQuestion('c1')).toBe('What happens at death?')
    expect(peekPendingQuestion('c2')).toBeNull()
    expect(takePendingQuestion('c1')).toBe('What happens at death?')
    expect(peekPendingQuestion()).toBeNull()
    expect(takePendingQuestion('c1')).toBeNull()
  })
})
