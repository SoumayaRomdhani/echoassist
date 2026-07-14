import type { CallEvent, CallStatus } from '@/lib/types'
import type { CallTransport } from '@/lib/ws'
import { SCREENING_DOMAIN, campaignByName, upsertCall, type MockCall } from './db'

interface LiveSpec {
  consent: boolean
  domain: string
  campaign: string
}

interface Turn {
  role: string
  text: string
  citations?: string[]
}

interface Scenario {
  status: CallStatus
  consentDecision: string
  consentGranted: boolean
  turns: Turn[]
  notes: Record<string, unknown> | null
  summary: string
}

interface ScriptEvent {
  type: CallEvent['type']
  data: Record<string, unknown>
  terminal?: boolean
}

// Calls started via the mock POST /calls are registered here so the transport
// knows to replay a live scenario (rather than treating the id as unknown).
const pending = new Map<string, LiveSpec>()

export function registerLiveCall(callId: string, spec: LiveSpec): void {
  pending.set(callId, spec)
}

function acceptedScenario(): Scenario {
  return {
    status: 'completed',
    consentDecision: 'accepted',
    consentGranted: true,
    notes: {
      candidate_name: 'Liam Carter',
      years_experience: 5,
      current_role: 'Full-stack Developer',
      key_skills: ['TypeScript', 'Node.js', 'React', 'AWS'],
      notice_period: '6 weeks',
      salary_expectation: '€78,000',
    },
    summary:
      'Liam Carter is a full-stack developer with five years of experience across TypeScript, Node.js and React. He can start in six weeks and expects around €78,000. He confirmed he is comfortable with the remote-first setup and the on-call rotation.',
    turns: [
      { role: 'assistant', text: SCREENING_DOMAIN.disclosure },
      { role: 'caller', text: 'Yes, that’s perfectly fine.' },
      { role: 'assistant', text: 'Thank you. Let’s get started with a few questions.' },
      { role: 'assistant', text: 'Could you tell me your full name?' },
      { role: 'caller', text: 'Liam Carter.' },
      { role: 'assistant', text: 'How many years of experience do you have?' },
      { role: 'caller', text: 'Five years, full-stack.' },
      { role: 'assistant', text: 'What technologies do you work with most?' },
      { role: 'caller', text: 'TypeScript and Node on the backend, React on the front, deployed on AWS.' },
      {
        role: 'assistant',
        text: 'We’re a remote-first team with a weekly on-call rotation, compensated as time off in lieu. Does that work for you?',
        citations: ['compensation_and_benefits.md'],
      },
      { role: 'caller', text: 'Yes, that works well for me.' },
      { role: 'assistant', text: 'Finally, what’s your notice period and salary expectation?' },
      { role: 'caller', text: 'Six weeks notice, and around seventy-eight thousand euros.' },
      { role: 'assistant', text: 'Thank you, Liam. That’s everything I needed — we’ll be in touch soon.' },
    ],
  }
}

function declinedScenario(): Scenario {
  return {
    status: 'declined',
    consentDecision: 'declined',
    consentGranted: false,
    notes: null,
    summary: 'Call ended: consent not granted.',
    turns: [
      { role: 'assistant', text: SCREENING_DOMAIN.disclosure },
      { role: 'caller', text: 'No, I’d prefer not to be recorded.' },
      {
        role: 'assistant',
        text: 'Understood. I won’t record anything and I’ll end the call here. Thank you for your time.',
      },
    ],
  }
}

function transcriptEvent(turn: Turn): ScriptEvent {
  return {
    type: 'transcript',
    data: { role: turn.role, text: turn.text, ...(turn.citations ? { citations: turn.citations } : {}) },
  }
}

function stateEvent(state: string, extra: Record<string, unknown> = {}): ScriptEvent {
  return { type: 'agent_state', data: { state, ...extra } }
}

/**
 * Expand a scenario into the wire event sequence, interleaving `agent_state`
 * events so the live orb animates through listening → thinking → speaking exactly
 * as the real pipeline will drive it. Assistant turns are `speaking`; caller turns
 * are preceded by `listening`; a `thinking` beat sits between a caller answer and
 * the next agent line. Structured-interview turns also carry question progress.
 */
function toEvents(scenario: Scenario): ScriptEvent[] {
  const events: ScriptEvent[] = [{ type: 'status', data: { status: 'started' } }]

  // turns[0..2] = disclosure (agent), consent answer (caller), acknowledgement (agent).
  events.push(stateEvent('speaking'), transcriptEvent(scenario.turns[0]))
  events.push(stateEvent('listening'), transcriptEvent(scenario.turns[1]))
  events.push(stateEvent('thinking'), stateEvent('speaking'), transcriptEvent(scenario.turns[2]))
  events.push({
    type: 'consent',
    data: { decision: scenario.consentDecision, granted: scenario.consentGranted },
  })

  if (!scenario.consentGranted) {
    events.push(stateEvent('idle'))
    events.push({ type: 'status', data: { status: 'declined' }, terminal: true })
    return events
  }

  events.push({ type: 'status', data: { status: 'interviewing' } })

  const interview = scenario.turns.slice(3)
  const questionTotal = interview.filter((t) => t.role === 'assistant').length
  let questionIndex = 0
  for (const turn of interview) {
    if (turn.role === 'assistant') {
      questionIndex += 1
      events.push(
        stateEvent('speaking', { question_index: questionIndex, question_total: questionTotal }),
        transcriptEvent(turn),
      )
    } else {
      events.push(stateEvent('listening'), transcriptEvent(turn), stateEvent('thinking'))
    }
  }

  events.push(stateEvent('idle'))
  events.push({ type: 'notes', data: { notes: scenario.notes } })
  events.push({ type: 'summary', data: { summary: scenario.summary } })
  events.push({ type: 'status', data: { status: 'completed' }, terminal: true })
  return events
}

function persistedFrom(callId: string, spec: LiveSpec, scenario: Scenario): MockCall {
  const campaign = campaignByName(spec.campaign)
  const createdAt = new Date().toISOString()
  return {
    call_id: callId,
    campaign_id: campaign.id,
    campaign_name: campaign.name,
    domain: spec.domain,
    status: scenario.status,
    consent_granted: scenario.consentGranted,
    created_at: createdAt,
    has_notes: scenario.notes !== null,
    has_summary: scenario.summary.length > 0,
    // Persisted transcript drops citations (backend keeps them in metadata only).
    transcript: scenario.turns.map((turn, ordinal) => ({
      ordinal,
      role: turn.role,
      text: turn.text,
    })),
    notes: scenario.notes,
    summary: scenario.summary,
    consent_log: [
      {
        call_id: callId,
        domain: spec.domain,
        decision: scenario.consentDecision,
        granted: scenario.consentGranted,
        disclosure_hash:
          'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2',
        created_at: createdAt,
      },
    ],
  }
}

const FIRST_DELAY = 300
const STEP = 550

/** Mock implementation of the live-event transport, used when VITE_USE_MOCKS is on. */
export const mockTransport: CallTransport = (callId, { onEvent, onOpen, onClose }) => {
  let cancelled = false
  const timers: ReturnType<typeof setTimeout>[] = []
  const schedule = (ms: number, fn: () => void) => {
    timers.push(
      setTimeout(() => {
        if (!cancelled) fn()
      }, ms),
    )
  }

  schedule(40, () => onOpen?.())

  const spec = pending.get(callId)
  if (!spec) {
    // Unknown / historical call: no live stream — let the page use the persisted GET.
    schedule(100, () => onClose?.({ code: 1000 }))
    return () => {
      cancelled = true
      timers.forEach(clearTimeout)
    }
  }
  pending.delete(callId)

  const scenario = spec.consent ? acceptedScenario() : declinedScenario()
  const events = toEvents(scenario)
  let seq = 0

  events.forEach((event, index) => {
    schedule(FIRST_DELAY + index * STEP, () => {
      // Persist just before the terminal event fires. The terminal event sets
      // live.done, which triggers the GET refetch — so the record must already
      // exist (this matches the backend, which finalizes/persists before it
      // publishes the terminal status).
      if (event.terminal) upsertCall(persistedFrom(callId, spec, scenario))
      seq += 1
      onEvent({
        call_id: callId,
        type: event.type,
        seq,
        ts: Date.now() / 1000,
        data: event.data,
        terminal: Boolean(event.terminal),
      })
    })
  })

  schedule(FIRST_DELAY + events.length * STEP, () => onClose?.({ code: 1000 }))

  return () => {
    cancelled = true
    timers.forEach(clearTimeout)
  }
}
