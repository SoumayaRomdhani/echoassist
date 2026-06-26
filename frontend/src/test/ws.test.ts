import { describe, expect, it } from 'vitest'
import { foldEvent, initialLiveState } from '@/lib/ws'
import type { CallEvent } from '@/lib/types'

function event(partial: Partial<CallEvent> & Pick<CallEvent, 'type'>): CallEvent {
  return { call_id: 'c1', seq: 1, ts: 0, data: {}, terminal: false, ...partial }
}

describe('foldEvent', () => {
  it('accumulates transcript turns with incrementing ordinals and citations', () => {
    let state = initialLiveState
    state = foldEvent(state, event({ type: 'transcript', data: { role: 'assistant', text: 'hi' } }))
    state = foldEvent(
      state,
      event({ type: 'transcript', data: { role: 'caller', text: 'yes', citations: ['a.md'] } }),
    )
    expect(state.turns).toHaveLength(2)
    expect(state.turns[0]).toMatchObject({ ordinal: 0, role: 'assistant', text: 'hi' })
    expect(state.turns[1]).toMatchObject({ ordinal: 1, role: 'caller', citations: ['a.md'] })
  })

  it('tracks status and marks done on a terminal event', () => {
    let state = initialLiveState
    state = foldEvent(state, event({ type: 'status', data: { status: 'interviewing' } }))
    expect(state.status).toBe('interviewing')
    expect(state.done).toBe(false)
    state = foldEvent(state, event({ type: 'status', data: { status: 'completed' }, terminal: true }))
    expect(state.status).toBe('completed')
    expect(state.done).toBe(true)
  })

  it('captures consent, notes, summary and error', () => {
    let state = initialLiveState
    state = foldEvent(state, event({ type: 'consent', data: { decision: 'accepted', granted: true } }))
    state = foldEvent(state, event({ type: 'notes', data: { notes: { name: 'X' } } }))
    state = foldEvent(state, event({ type: 'summary', data: { summary: 'done' } }))
    expect(state.consent).toEqual({ decision: 'accepted', granted: true })
    expect(state.notes).toEqual({ name: 'X' })
    expect(state.summary).toBe('done')

    state = foldEvent(
      state,
      event({ type: 'error', data: { message: 'boom', persisted: true }, terminal: true }),
    )
    expect(state.error).toEqual({ message: 'boom', persisted: true })
    expect(state.done).toBe(true)
  })
})
