import { delay, http, HttpResponse } from 'msw'
import type {
  DocumentUploadOut,
  HealthOut,
  Question,
  StartCallResponse,
} from '@/lib/types'
import {
  DEFAULT_CAMPAIGN,
  SCREENING_DOMAIN,
  createJobPosting,
  db,
  getCall,
  getJobPosting,
  listCalls,
  listJobPostings,
  newCallId,
  updateJobPosting,
} from './db'
import { registerLiveCall } from './mockCallStream'

function notFound(detail: string) {
  return HttpResponse.json({ detail }, { status: 404 })
}

const READY: HealthOut = {
  status: 'ok',
  service: 'echoassist-backend',
  components: { database: 'ok', redis: 'ok', qdrant: 'ok' },
}

export const handlers = [
  http.get('*/ready', () => HttpResponse.json(READY)),
  http.get('*/health', () =>
    HttpResponse.json({ status: 'ok', service: 'echoassist-backend', components: {} }),
  ),

  http.get('*/domains', async () => {
    await delay(150)
    return HttpResponse.json(db.domains)
  }),
  http.get('*/domains/:domain', ({ params }) => {
    const domain = db.domains.find((item) => item.name === params.domain)
    return domain ? HttpResponse.json(domain) : notFound(`domain '${params.domain}' not found`)
  }),

  http.get('*/campaigns', () => HttpResponse.json(db.campaigns)),

  http.get('*/calls', ({ request }) => {
    const url = new URL(request.url)
    const limit = Number(url.searchParams.get('limit') ?? 50)
    const offset = Number(url.searchParams.get('offset') ?? 0)
    const { items, total } = listCalls({
      domain: url.searchParams.get('domain'),
      campaignId: url.searchParams.has('campaign_id')
        ? Number(url.searchParams.get('campaign_id'))
        : null,
      limit,
      offset,
    })
    return HttpResponse.json({ items, total, limit, offset })
  }),

  // The mock live stream is client-side (mockCallStream), so there is no server-side
  // live registry to surface — the demo opens the call detail directly on start. Return
  // an empty list so the live banner poll is a clean no-op offline. (Declared before
  // `/calls/:id` so it isn't captured as id="live".)
  http.get('*/calls/live', () => HttpResponse.json([])),

  http.get('*/calls/:id/consent', ({ params }) => {
    const call = getCall(String(params.id))
    return HttpResponse.json(call?.consent_log ?? [])
  }),
  http.get('*/calls/:id/notes', ({ params }) => {
    const call = getCall(String(params.id))
    if (!call) return notFound(`call ${params.id} not found`)
    if (!call.notes) return notFound(`call ${params.id} has no notes`)
    return HttpResponse.json({ call_id: call.call_id, notes: call.notes })
  }),
  http.get('*/calls/:id/summary', ({ params }) => {
    const call = getCall(String(params.id))
    if (!call) return notFound(`call ${params.id} not found`)
    if (!call.summary) return notFound(`call ${params.id} has no summary`)
    return HttpResponse.json({ call_id: call.call_id, summary: call.summary })
  }),
  http.get('*/calls/:id', ({ params }) => {
    const call = getCall(String(params.id))
    return call ? HttpResponse.json(call) : notFound(`call ${params.id} not found`)
  }),

  http.post('*/calls', async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as {
      domain?: string
      campaign?: string
      consent?: boolean
      // Accepted for the tailored-interview flow; the canned mock stream ignores it.
      job_posting_id?: number
    }
    const callId = newCallId()
    const domain = body.domain ?? SCREENING_DOMAIN.name
    const campaign = body.campaign ?? DEFAULT_CAMPAIGN.name
    registerLiveCall(callId, { consent: body.consent ?? true, domain, campaign })
    const response: StartCallResponse = {
      call_id: callId,
      status: 'started',
      ws_url: `/ws/calls/${callId}`,
    }
    return HttpResponse.json(response, { status: 202 })
  }),

  // --- Job postings (JD-based interviews) --------------------------------- //
  http.get('*/job-postings', () => HttpResponse.json(listJobPostings())),
  http.post('*/job-postings', async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as {
      title?: string
      description?: string
      domain?: string
    }
    await delay(500) // simulate the LLM drafting questions
    const posting = createJobPosting({
      title: body.title ?? 'Untitled role',
      description: body.description ?? '',
      domain: body.domain,
    })
    return HttpResponse.json(posting, { status: 201 })
  }),
  http.get('*/job-postings/:id', ({ params }) => {
    const posting = getJobPosting(Number(params.id))
    return posting ? HttpResponse.json(posting) : notFound(`job posting ${params.id} not found`)
  }),
  http.patch('*/job-postings/:id', async ({ request, params }) => {
    const body = (await request.json().catch(() => ({}))) as {
      title?: string
      questions?: Question[]
      status?: 'draft' | 'confirmed'
    }
    const posting = updateJobPosting(Number(params.id), body)
    return posting ? HttpResponse.json(posting) : notFound(`job posting ${params.id} not found`)
  }),

  http.post('*/domains/:domain/documents', async ({ request, params }) => {
    const domain = db.domains.find((item) => item.name === params.domain)
    if (!domain) return notFound(`domain '${params.domain}' not found`)
    const form = await request.formData()
    const file = form.get('file')
    const filename = file instanceof File ? file.name : 'document.md'
    const size = file instanceof File ? file.size : 0
    const chunks = Math.max(1, Math.round(size / 800))
    domain.indexed = true
    await delay(400)
    const response: DocumentUploadOut = {
      domain: domain.name,
      filename,
      documents: 1,
      chunks,
      collection_count: 12 + chunks,
    }
    return HttpResponse.json(response, { status: 201 })
  }),
]
