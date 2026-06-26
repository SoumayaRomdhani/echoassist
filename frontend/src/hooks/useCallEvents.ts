import { useEffect, useReducer } from 'react'
import { getRuntime } from '@/lib/runtimeConfig'
import {
  foldEvent,
  initialLiveState,
  websocketTransport,
  type CallTransport,
  type LiveCallState,
} from '@/lib/ws'
import type { CallEvent } from '@/lib/types'

type Action =
  | { kind: 'event'; event: CallEvent }
  | { kind: 'connected'; value: boolean }
  | { kind: 'reset' }

function reducer(state: LiveCallState, action: Action): LiveCallState {
  switch (action.kind) {
    case 'event':
      return foldEvent(state, action.event)
    case 'connected':
      return { ...state, connected: action.value }
    case 'reset':
      return initialLiveState
  }
}

async function resolveTransport(): Promise<CallTransport> {
  if (getRuntime().useMocks) {
    return (await import('@/mocks/mockCallStream')).mockTransport
  }
  return websocketTransport
}

/**
 * Subscribe to a call's live event stream and fold it into UI state. When
 * `enabled` is false (or no id), it stays idle. Selects the WebSocket transport
 * in live mode and the in-browser mock transport when mocks are on.
 */
export function useCallEvents(callId: string | undefined, enabled: boolean): LiveCallState {
  const [state, dispatch] = useReducer(reducer, initialLiveState)

  useEffect(() => {
    if (!callId || !enabled) return

    let cancelled = false
    let unsubscribe: (() => void) | undefined
    dispatch({ kind: 'reset' })

    void resolveTransport().then((transport) => {
      if (cancelled) return
      unsubscribe = transport(callId, {
        onEvent: (event) => dispatch({ kind: 'event', event }),
        onOpen: () => dispatch({ kind: 'connected', value: true }),
        onClose: () => dispatch({ kind: 'connected', value: false }),
      })
    })

    return () => {
      cancelled = true
      unsubscribe?.()
    }
  }, [callId, enabled])

  return state
}
