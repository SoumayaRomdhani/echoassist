import type { CallOut, CallStatus } from '@/lib/types'

const STATUSES: CallStatus[] = ['started', 'interviewing', 'completed', 'declined', 'failed']

export interface CallMetrics {
  total: number
  byStatus: Record<CallStatus, number>
  completed: number
  consentRate: number
  notesCoverage: number
  summaryCoverage: number
}

/** Derive operational metrics from a page of calls. Pure — easy to unit test. */
export function computeMetrics(calls: CallOut[]): CallMetrics {
  const byStatus = Object.fromEntries(STATUSES.map((status) => [status, 0])) as Record<
    CallStatus,
    number
  >
  let consented = 0
  let notes = 0
  let summary = 0

  for (const call of calls) {
    byStatus[call.status] = (byStatus[call.status] ?? 0) + 1
    if (call.consent_granted) consented += 1
    if (call.has_notes) notes += 1
    if (call.has_summary) summary += 1
  }

  const total = calls.length
  const ratio = (value: number) => (total === 0 ? 0 : value / total)

  return {
    total,
    byStatus,
    completed: byStatus.completed,
    consentRate: ratio(consented),
    notesCoverage: ratio(notes),
    summaryCoverage: ratio(summary),
  }
}
