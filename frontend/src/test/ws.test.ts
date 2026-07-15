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

  it('tracks agent state, volume and interview progress', () => {
    let state = initialLiveState
    expect(state.agentState).toBe('idle')

    state = foldEvent(
      state,
      event({
        type: 'agent_state',
        data: { state: 'speaking', volume: 0.7, question_index: 2, question_total: 5 },
      }),
    )
    expect(state.agentState).toBe('speaking')
    expect(state.volume).toBe(0.7)
    expect(state.progress).toEqual({ index: 2, total: 5 })

    // An unknown state is ignored; progress persists when the next event omits it.
    state = foldEvent(state, event({ type: 'agent_state', data: { state: 'bogus' } }))
    expect(state.agentState).toBe('speaking')
    expect(state.progress).toEqual({ index: 2, total: 5 })
    expect(state.volume).toBeNull()
  })

  it('types a live partial (caller or agent), then the final turn supersedes it', () => {
    let state = initialLiveState
    state = foldEvent(state, event({ type: 'partial_transcript', data: { role: 'caller', text: 'I have five' } }))
    expect(state.partial).toEqual({ role: 'caller', text: 'I have five' })
    expect(state.turns).toHaveLength(0)

    state = foldEvent(state, event({ type: 'partial_transcript', data: { role: 'caller', text: 'I have five years' } }))
    expect(state.partial).toEqual({ role: 'caller', text: 'I have five years' })

    // The finalized turn lands and clears the partial.
    state = foldEvent(state, event({ type: 'transcript', data: { role: 'caller', text: 'I have five years.' } }))
    expect(state.partial).toBeNull()
    expect(state.turns).toHaveLength(1)

    // The agent's reply also streams as a partial, on the assistant side.
    state = foldEvent(state, event({ type: 'partial_transcript', data: { role: 'assistant', text: 'Thank' } }))
    expect(state.partial).toEqual({ role: 'assistant', text: 'Thank' })
    state = foldEvent(state, event({ type: 'transcript', data: { role: 'assistant', text: 'Thank you.' } }))
    expect(state.partial).toBeNull()
  })

  it('settles the agent orb to idle when the call ends', () => {
    let state = foldEvent(initialLiveState, event({ type: 'agent_state', data: { state: 'speaking' } }))
    expect(state.agentState).toBe('speaking')
    state = foldEvent(state, event({ type: 'status', data: { status: 'completed' }, terminal: true }))
    expect(state.agentState).toBe('idle')
    expect(state.done).toBe(true)
  })
})
