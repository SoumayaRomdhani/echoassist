import { getRuntime, wsBaseUrl } from './runtimeConfig'
import type { CallEvent, CallStatus, TranscriptTurnOut } from './types'

/** Derive the WebSocket URL for a call from the configured base URL. */
export function callWsUrl(callId: string): string {
  return `${wsBaseUrl()}/ws/calls/${callId}`
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
}

/** Pure reducer: apply one `CallEvent` to the folded state. */
export function foldEvent(state: LiveCallState, event: CallEvent): LiveCallState {
  switch (event.type) {
    case 'status':
      return {
        ...state,
        status: (event.data.status as CallStatus | undefined) ?? state.status,
        done: state.done || event.terminal,
      }
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
      return { ...state, turns: [...state.turns, turn] }
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
