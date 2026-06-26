import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CallList } from '@/features/calls/CallList'
import type { CallOut } from '@/lib/types'

function renderList(calls: CallOut[]) {
  return render(<CallList calls={calls} onSelect={vi.fn()} />)
}

const baseCall: CallOut = {
  call_id: 'abc12345def67890',
  campaign_id: 1,
  domain: 'screening',
  status: 'completed',
  consent_granted: true,
  created_at: new Date().toISOString(),
  has_notes: true,
  has_summary: true,
}

describe('CallList', () => {
  it('shows the empty state when there are no calls', () => {
    renderList([])
    expect(screen.getByText('No calls yet')).toBeInTheDocument()
  })

  it('renders a row per call with its status', () => {
    renderList([
      baseCall,
      { ...baseCall, call_id: 'zzz99999yyy11111', status: 'declined', consent_granted: false },
    ])
    expect(screen.getByText('Completed')).toBeInTheDocument()
    expect(screen.getByText('Declined')).toBeInTheDocument()
    expect(screen.getByText('No consent')).toBeInTheDocument()
  })
})
