import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { api } from '@/lib/api'
import type { JobPostingOut } from '@/lib/types'
import { server } from '@/mocks/server'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('job postings', () => {
  it('lists the seeded confirmed posting', async () => {
    const list = await api.get<JobPostingOut[]>('/job-postings')
    expect(list.some((p) => p.status === 'confirmed')).toBe(true)
  })

  it('generates a draft, then curates and confirms it', async () => {
    const created = await api.postJson<JobPostingOut>('/job-postings', {
      title: 'Data Engineer',
      description: 'Build ETL pipelines. Python, Airflow, dbt.',
    })
    expect(created.status).toBe('draft')
    expect(created.questions.length).toBeGreaterThan(0)
    expect(created.questions[0].id).toBe('q1')

    // Recruiter edits: keep+edit one, add one, and drop an empty one, then confirm.
    const updated = await api.patchJson<JobPostingOut>(`/job-postings/${created.id}`, {
      status: 'confirmed',
      questions: [
        { id: 'q1', text: 'How many years with Airflow?', slot: 'years_airflow', enabled: true },
        { id: null, text: 'Preferred data warehouse?', slot: null, enabled: true },
        { id: null, text: '', slot: null, enabled: true }, // empty -> dropped
      ],
    })
    expect(updated.status).toBe('confirmed')
    expect(updated.questions.map((q) => q.slot)).toEqual([
      'years_airflow',
      'preferred_data_warehouse',
    ])
    expect(updated.questions.map((q) => q.id)).toEqual(['q1', 'q2'])
  })

  it('404s for an unknown posting', async () => {
    await expect(api.get('/job-postings/9999')).rejects.toMatchObject({ status: 404 })
  })

  it('deletes a posting', async () => {
    const created = await api.postJson<JobPostingOut>('/job-postings', {
      title: 'Temp',
      description: 'to delete',
    })
    await api.del<void>(`/job-postings/${created.id}`)
    await expect(api.get(`/job-postings/${created.id}`)).rejects.toMatchObject({ status: 404 })
  })
})
