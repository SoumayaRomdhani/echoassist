import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { api } from '@/lib/api'
import type { DomainOut } from '@/lib/types'
import { server } from '@/mocks/server'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('api client', () => {
  it('returns parsed JSON for a successful GET', async () => {
    const domains = await api.get<DomainOut[]>('/domains')
    expect(Array.isArray(domains)).toBe(true)
    expect(domains[0]?.name).toBe('screening')
  })

  it('throws a typed ApiError carrying the backend detail on 404', async () => {
    await expect(api.get('/calls/does-not-exist')).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
    })
  })
})
