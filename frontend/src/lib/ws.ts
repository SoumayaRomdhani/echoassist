import { getRuntime, wsBaseUrl } from './runtimeConfig'
import type { AgentState, CallEvent, CallStatus, TranscriptTurnOut } from './types'

/** Derive the WebSocket URL for a call from the configured base URL. */
export function callWsUrl(callId: string): string {
  return `${wsBaseUrl()}/ws/calls/${callId}`
}

/** Live interview progress: which structured question we're on, out of how many. */
export interface CallProgress {
  index: number
  total: number
}

/** Folded view of a call's live event stream. */
export interface LiveCallState {
  connected: boolean
  done: boolean
  status: CallStatus | null
  turns: TranscriptTurnOut[]
  consent: { decision: string; granted: boolean } | null
  notes: Record<string, unknown> | null
  summary: string | null
  degraded: { reason?: string } | null
  error: { message: string; persisted?: boolean } | null
  /** The agent's current turn phase (drives the ambient orb + status text). */
  agentState: AgentState
  /** Latest speaking amplitude 0–1, for an audio-reactive orb. Absent ⇒ synthesized. */
  volume: number | null
  /** Structured-interview progress, when known. */
  progress: CallProgress | null
  /**
   * A turn being produced live — the caller's words as they speak (interim STT) or the
   * agent's reply as the LLM writes it — shown as a typing bubble until the final turn lands.
   */
  partial: { role: string; text: string } | null
  /** The current pipeline sub-step ("Searching the knowledge base…"), for the labor-illusion UI. */
  agentStep: string | null
}

export const initialLiveState: LiveCallState = {
  connected: false,
  done: false,
  status: null,
  turns: [],
  consent: null,
  notes: null,
  summary: null,
  degraded: null,
  error: null,
  agentState: 'idle',
  volume: null,
  progress: null,
  partial: null,
  agentStep: null,
}

const AGENT_STATES: readonly AgentState[] = ['idle', 'listening', 'thinking', 'speaking']

function asAgentState(value: unknown): AgentState | null {
  return AGENT_STATES.includes(value as AgentState) ? (value as AgentState) : null
}

function asProgress(data: Record<string, unknown>): CallProgress | null {
  const index = data.question_index
  const total = data.question_total
  if (typeof index === 'number' && typeof total === 'number' && total > 0) {
    return { index, total }
  }
  return null
}

/** Pure reducer: apply one `CallEvent` to the folded state. */
export function foldEvent(state: LiveCallState, event: CallEvent): LiveCallState {
  switch (event.type) {
    case 'status': {
      const done = state.done || event.terminal
      return {
        ...state,
        status: (event.data.status as CallStatus | undefined) ?? state.status,
        done,
        // A finished call has no active agent phase — settle the orb, drop any partial/step.
        agentState: done ? 'idle' : state.agentState,
        partial: done ? null : state.partial,
        agentStep: done ? null : state.agentStep,
      }
    }
    case 'agent_state': {
      const next = asAgentState(event.data.state)
      const volume = typeof event.data.volume === 'number' ? event.data.volume : null
      // A new turn (back to listening) or an idle gap clears the previous sub-step.
      const resetsStep = next === 'listening' || next === 'idle'
      return {
        ...state,
        agentState: next ?? state.agentState,
        volume,
        progress: asProgress(event.data) ?? state.progress,
        agentStep: resetsStep ? null : state.agentStep,
      }
    }
    case 'agent_step':
      return { ...state, agentStep: String(event.data.label ?? '') || null }
    case 'transcript': {
      const citations = Array.isArray(event.data.citations)
        ? (event.data.citations as string[])
        : undefined
      const turn: TranscriptTurnOut = {
        ordinal: state.turns.length,
        role: String(event.data.role ?? ''),
        text: String(event.data.text ?? ''),
        ...(citations ? { citations } : {}),
      }
      // The finalized turn supersedes any interim partial (caller or agent).
      return { ...state, turns: [...state.turns, turn], partial: null }
    }
    case 'partial_transcript': {
      const text = String(event.data.text ?? '')
      const role = String(event.data.role ?? 'caller')
      return { ...state, partial: text ? { role, text } : null }
    }
    case 'consent':
      return {
        ...state,
        consent: {
          decision: String(event.data.decision ?? ''),
          granted: Boolean(event.data.granted),
        },
      }
    case 'notes':
      return { ...state, notes: (event.data.notes as Record<string, unknown> | null) ?? null }
    case 'summary':
      return { ...state, summary: (event.data.summary as string | null) ?? null }
    case 'degraded':
      return { ...state, degraded: { reason: event.data.reason as string | undefined } }
    case 'error':
      return {
        ...state,
        error: {
          message: String(event.data.message ?? 'call error'),
          persisted: Boolean(event.data.persisted),
        },
        done: true,
        agentState: 'idle',
      }
    default:
      return state
  }
}

export interface CallTransportHandlers {
  onEvent: (event: CallEvent) => void
  onOpen?: () => void
  onClose?: (info: { code?: number }) => void
}

/** A live-event source for a call. Returns an unsubscribe function. */
export type CallTransport = (callId: string, handlers: CallTransportHandlers) => () => void

/** Production transport: a real WebSocket to the backend (replay-then-live). */
export const websocketTransport: CallTransport = (callId, { onEvent, onOpen, onClose }) => {
  let socket: WebSocket | null = null
  let closed = false

  // Resolve the (optional, possibly async) auth token before opening, then pass
  // it as a query param — WebSocket cannot send Authorization headers.
  void Promise.resolve(getRuntime().getAuthToken()).then((token) => {
    if (closed) return
    const url = `${callWsUrl(callId)}${token ? `?access_token=${encodeURIComponent(token)}` : ''}`
    socket = new WebSocket(url)
    socket.addEventListener('open', () => onOpen?.())
    socket.addEventListener('message', (ev) => {
      try {
        onEvent(JSON.parse(ev.data as string) as CallEvent)
      } catch {
        /* ignore a malformed frame */
      }
    })
    socket.addEventListener('close', (ev) => onClose?.({ code: ev.code }))
  })

  return () => {
    closed = true
    try {
      socket?.close()
    } catch {
      /* already closed */
    }
  }
}
