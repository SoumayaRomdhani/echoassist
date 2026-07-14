/**
 * TypeScript mirrors of the backend's stable API contract.
 *
 * These match the Pydantic DTOs in `backend/src/api/schemas.py` and the live
 * `CallEvent` shape in `backend/src/api/events.py` exactly. Timestamps arrive as
 * ISO-8601 strings over JSON.
 */

export type CallStatus = 'started' | 'interviewing' | 'completed' | 'declined' | 'failed'

export interface DomainOut {
  name: string
  language: string
  disclosure: string
  greeting: string
  question_count: number
  slots: string[]
  /** Whether a non-empty vector collection exists; null when undeterminable. */
  indexed: boolean | null
}

export interface CampaignOut {
  id: number
  name: string
  domain: string
  created_at: string
}

export interface TranscriptTurnOut {
  ordinal: number
  role: string
  text: string
  /** Citations are surfaced live; the persisted transcript omits them. */
  citations?: string[]
}

export interface CallOut {
  call_id: string
  campaign_id: number
  domain: string
  status: CallStatus
  consent_granted: boolean
  created_at: string
  has_notes: boolean
  has_summary: boolean
}

export interface CallDetailOut extends CallOut {
  campaign_name: string
  transcript: TranscriptTurnOut[]
  notes: Record<string, unknown> | null
  summary: string | null
}

export interface CallListOut {
  items: CallOut[]
  total: number
  limit: number
  offset: number
}

export interface ConsentLogOut {
  call_id: string
  domain: string
  decision: string
  granted: boolean
  disclosure_hash: string | null
  created_at: string
}

export interface StartCallRequest {
  domain?: string
  campaign?: string
  consent: boolean
}

export interface StartCallResponse {
  call_id: string
  status: string
  ws_url: string
}

export interface SkippedDocument {
  source: string
  reason: string
}

export interface DocumentUploadOut {
  domain: string
  filename: string
  documents: number
  chunks: number
  collection_count: number
  skipped?: SkippedDocument[]
}

export interface DocumentInfo {
  source: string
  size_bytes: number
  modified_at: string
  chunks: number | null
}

export interface DocumentListOut {
  domain: string
  documents: DocumentInfo[]
}

export interface DocumentDeleteOut {
  domain: string
  filename: string
  file_removed: boolean
  chunks_removed: number
}

export interface DomainReindexOut {
  domain: string
  documents: number
  chunks: number
  collection_count: number
  skipped?: SkippedDocument[]
}

export interface RetrievedChunk {
  source: string
  score: number
  page: number | null
  heading: string | null
  snippet: string
}

export interface SearchPreviewOut {
  domain: string
  query: string
  results: RetrievedChunk[]
}

export interface HealthOut {
  status: 'ok' | 'degraded'
  service: string
  components: Record<string, string>
}

export interface NotesOut {
  call_id: string
  notes: Record<string, unknown>
}

export interface SummaryOut {
  call_id: string
  summary: string
}

// --- WebSocket live events (backend/src/api/events.py + runner.py) --------- //
export type CallEventType =
  | 'status'
  | 'transcript'
  | 'consent'
  | 'notes'
  | 'summary'
  | 'degraded'
  | 'error'
  | 'agent_state'

/**
 * The agent's live turn phase, surfaced by the `agent_state` event so the UI can
 * render an ambient indicator (orb) and status text. Mirrors the phases a voice
 * pipeline moves through each turn: waiting for the caller (`listening`), running
 * STT/LLM/RAG (`thinking`), playing the reply (`speaking`), or between turns (`idle`).
 */
export type AgentState = 'idle' | 'listening' | 'thinking' | 'speaking'

export interface CallEvent {
  call_id: string
  type: CallEventType
  seq: number
  ts: number
  data: Record<string, unknown>
  terminal: boolean
}
