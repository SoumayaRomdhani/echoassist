import { describe, expect, it } from 'vitest'
import { computeMetrics } from '@/features/metrics/metrics'
import type { CallOut } from '@/lib/types'

function call(partial: Partial<CallOut>): CallOut {
  return {
    call_id: 'x',
    campaign_id: 1,
    domain: 'screening',
    status: 'completed',
    consent_granted: true,
    created_at: new Date().toISOString(),
    has_notes: true,
    has_summary: true,
    ...partial,
  }
}

describe('computeMetrics', () => {
  it('returns zeros for an empty list', () => {
    const metrics = computeMetrics([])
    expect(metrics.total).toBe(0)
    expect(metrics.completed).toBe(0)
    expect(metrics.consentRate).toBe(0)
  })

  it('aggregates statuses, consent and coverage', () => {
    const calls = [
      call({ status: 'completed', consent_granted: true, has_notes: true, has_summary: true }),
      call({ status: 'declined', consent_granted: false, has_notes: false, has_summary: true }),
      call({ status: 'failed', consent_granted: true, has_notes: false, has_summary: false }),
      call({ status: 'completed', consent_granted: true, has_notes: true, has_summary: true }),
    ]
    const metrics = computeMetrics(calls)
    expect(metrics.total).toBe(4)
    expect(metrics.completed).toBe(2)
    expect(metrics.byStatus.declined).toBe(1)
    expect(metrics.byStatus.failed).toBe(1)
    expect(metrics.consentRate).toBeCloseTo(0.75)
    expect(metrics.notesCoverage).toBeCloseTo(0.5)
    expect(metrics.summaryCoverage).toBeCloseTo(0.75)
  })
})
