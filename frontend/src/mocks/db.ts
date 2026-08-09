import type {
  CallDetailOut,
  CallOut,
  CallStatus,
  CampaignOut,
  ConsentLogOut,
  DomainOut,
  JobPostingOut,
  JobPostingStatus,
  Question,
  TranscriptTurnOut,
} from '@/lib/types'

/** A call record in the mock store: the full detail plus its consent audit trail. */
export interface MockCall extends CallDetailOut {
  consent_log: ConsentLogOut[]
}

const HOUR = 3_600_000
const NOW = Date.now()
const iso = (hoursAgo: number) => new Date(NOW - hoursAgo * HOUR).toISOString()

export const SCREENING_DOMAIN: DomainOut = {
  name: 'screening',
  language: 'en',
  disclosure:
    'Hi, this is EchoAssist, an AI voice assistant calling on behalf of ACTEEK. This call will be recorded so I can take accurate notes. Is that okay with you?',
  greeting:
    'Thanks for taking the time to speak with me today — this should only take about ten minutes.',
  question_count: 6,
  slots: [
    'candidate_name',
    'years_experience',
    'current_role',
    'key_skills',
    'notice_period',
    'salary_expectation',
  ],
  indexed: true,
}

export const DEFAULT_CAMPAIGN: CampaignOut = {
  id: 1,
  name: 'Screening — default campaign',
  domain: 'screening',
  created_at: iso(96),
}

type Tuple = [role: string, text: string, citations?: string[]]

function transcript(tuples: Tuple[]): TranscriptTurnOut[] {
  return tuples.map(([role, text, citations], ordinal) => ({
    ordinal,
    role,
    text,
    ...(citations ? { citations } : {}),
  }))
}

function consentEntry(
  callId: string,
  granted: boolean,
  hoursAgo: number,
): ConsentLogOut {
  return {
    call_id: callId,
    domain: 'screening',
    decision: granted ? 'accepted' : 'declined',
    granted,
    disclosure_hash: 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2',
    created_at: iso(hoursAgo),
  }
}

function completedCall(args: {
  id: string
  hoursAgo: number
  notes: Record<string, unknown>
  summary: string
  turns: Tuple[]
}): MockCall {
  return {
    call_id: args.id,
    campaign_id: DEFAULT_CAMPAIGN.id,
    campaign_name: DEFAULT_CAMPAIGN.name,
    domain: 'screening',
    status: 'completed',
    consent_granted: true,
    created_at: iso(args.hoursAgo),
    has_notes: true,
    has_summary: true,
    transcript: transcript(args.turns),
    notes: args.notes,
    summary: args.summary,
    consent_log: [consentEntry(args.id, true, args.hoursAgo)],
  }
}

const seededCalls: MockCall[] = [
  completedCall({
    id: 'a17c9f2e4b8d4e1a9c3f5b7d2e6a8c40',
    hoursAgo: 3,
    notes: {
      candidate_name: 'Sarah Müller',
      years_experience: 6,
      current_role: 'Senior Backend Engineer',
      key_skills: ['Python', 'FastAPI', 'PostgreSQL', 'Kubernetes'],
      notice_period: '1 month',
      salary_expectation: '€85,000',
    },
    summary:
      'Sarah Müller is a senior backend engineer with six years of experience, strong in Python, FastAPI and PostgreSQL. She is available within one month and her salary expectation is around €85,000. She confirmed she is comfortable with remote-first work and on-call rotations.',
    turns: [
      ['assistant', SCREENING_DOMAIN.disclosure],
      ['caller', 'Yes, that works for me.'],
      ['assistant', 'Thank you. Let me begin with a few quick questions.'],
      ['assistant', 'Could you start by telling me your full name?'],
      ['caller', 'Sarah Müller.'],
      ['assistant', 'How many years of professional backend experience do you have?'],
      ['caller', 'About six years now.'],
      ['assistant', 'What is your current role?'],
      ['caller', "I'm a senior backend engineer at a fintech company."],
      [
        'assistant',
        'Our team works remote-first with a weekly on-call rotation. The handbook notes on-call is compensated as time off in lieu. Does that arrangement work for you?',
        ['compensation_and_benefits.md'],
      ],
      ['caller', "Yes, that's fine — I've done on-call before."],
      ['assistant', 'Great. What is your notice period and your salary expectation?'],
      ['caller', 'One month notice, and I’m looking for around eighty-five thousand euros.'],
      ['assistant', 'Thank you, Sarah. That’s everything I needed — we’ll be in touch shortly.'],
    ],
  }),
  completedCall({
    id: 'b28d0a3f5c9e4f2b0d4a6c8e3f7b9d51',
    hoursAgo: 8,
    notes: {
      candidate_name: 'Daniel Okoro',
      years_experience: 3,
      current_role: 'Frontend Developer',
      key_skills: ['TypeScript', 'React', 'Tailwind CSS'],
      notice_period: '2 weeks',
      salary_expectation: '€60,000',
    },
    summary:
      'Daniel Okoro is a frontend developer with three years of experience focused on TypeScript and React. He can start within two weeks and expects around €60,000. He was particularly interested in the design-system work.',
    turns: [
      ['assistant', SCREENING_DOMAIN.disclosure],
      ['caller', 'Sure, go ahead.'],
      ['assistant', 'Thank you. First, could you tell me your full name?'],
      ['caller', 'Daniel Okoro.'],
      ['assistant', 'How many years of frontend experience do you have?'],
      ['caller', 'Three years.'],
      ['assistant', 'What technologies do you work with most?'],
      ['caller', 'Mostly TypeScript, React, and Tailwind.'],
      ['assistant', 'What is your notice period and expected salary?'],
      ['caller', 'Two weeks, and about sixty thousand euros.'],
      ['assistant', 'Perfect, thank you Daniel. We’ll follow up by email.'],
    ],
  }),
  {
    call_id: 'c39e1b4a6d0f5a3c1e5b7d9f4a8c0e62',
    campaign_id: DEFAULT_CAMPAIGN.id,
    campaign_name: DEFAULT_CAMPAIGN.name,
    domain: 'screening',
    status: 'declined',
    consent_granted: false,
    created_at: iso(20),
    has_notes: false,
    has_summary: true,
    transcript: transcript([
      ['assistant', SCREENING_DOMAIN.disclosure],
      ['caller', "No, I'd rather not be recorded."],
      ['assistant', 'Understood. I won’t record anything and I’ll end the call here. Thank you for your time.'],
    ]),
    notes: null,
    summary: 'Call ended: consent not granted.',
    consent_log: [consentEntry('c39e1b4a6d0f5a3c1e5b7d9f4a8c0e62', false, 20)],
  },
  {
    call_id: 'd40f2c5b7e1a6b4d2f6c8e0a5b9d1f73',
    campaign_id: DEFAULT_CAMPAIGN.id,
    campaign_name: DEFAULT_CAMPAIGN.name,
    domain: 'screening',
    status: 'failed',
    consent_granted: true,
    created_at: iso(28),
    has_notes: false,
    has_summary: true,
    transcript: transcript([
      ['assistant', SCREENING_DOMAIN.disclosure],
      ['caller', 'Yes, that’s fine.'],
      ['assistant', 'Thank you. Could you tell me your full name?'],
      ['caller', 'Priya Nair.'],
    ]),
    notes: null,
    summary: 'Call failed: provider quota exceeded.',
    consent_log: [consentEntry('d40f2c5b7e1a6b4d2f6c8e0a5b9d1f73', true, 28)],
  },
  completedCall({
    id: 'e51a3d6c8f2b7c5e3a7d9f1b6c0e2a84',
    hoursAgo: 49,
    notes: {
      candidate_name: 'Marco Rossi',
      years_experience: 9,
      current_role: 'Engineering Manager',
      key_skills: ['Leadership', 'Go', 'Distributed Systems'],
      notice_period: '3 months',
      salary_expectation: '€110,000',
    },
    summary:
      'Marco Rossi is an engineering manager with nine years of experience and a background in Go and distributed systems. His notice period is three months and he expects around €110,000. He is motivated by team-building and platform reliability work.',
    turns: [
      ['assistant', SCREENING_DOMAIN.disclosure],
      ['caller', 'Yes, absolutely.'],
      ['assistant', 'Thank you. Could you tell me your full name and current role?'],
      ['caller', 'Marco Rossi — I’m an engineering manager.'],
      ['assistant', 'How many years of experience do you have in total?'],
      ['caller', 'Nine years, the last three in management.'],
      ['assistant', 'What is your notice period and salary expectation?'],
      ['caller', 'Three months, and around a hundred and ten thousand euros.'],
      ['assistant', 'Thank you, Marco. That’s everything — we’ll be in touch.'],
    ],
  }),
]

// --- Job postings (JD-based interviews) ----------------------------------- //
const MAX_GENERATED = 8
const MAX_CURATED = 20

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 40)
    .replace(/_+$/g, '')
}

/** Mirror the backend's normalize_questions: q{n} ids, unique slugified slots, enabled kept. */
function normalizeQuestions(
  raw: { text?: string; slot?: string | null; enabled?: boolean }[],
  max: number,
): Question[] {
  const used = new Set<string>()
  const out: Question[] = []
  for (const item of raw) {
    const text = (item.text ?? '').trim().slice(0, 300)
    if (!text) continue
    let slot = slugify(item.slot ?? '') || slugify(text) || 'question'
    const base = slot
    let n = 2
    while (used.has(slot)) slot = `${base}_${n++}`.slice(0, 40)
    used.add(slot)
    out.push({ id: `q${out.length + 1}`, text, slot, enabled: item.enabled ?? true })
    if (out.length >= max) break
  }
  return out
}

/** A stand-in for the LLM: draft plausible screening questions from a description. */
function generateMockQuestions(description: string): Question[] {
  const role = description.split(/[.\n]/)[0]?.trim().slice(0, 60) || 'this role'
  return normalizeQuestions(
    [
      { text: `How many years of experience do you have relevant to ${role}?` },
      { text: 'Walk me through a recent project you are proud of.' },
      { text: 'Which parts of our tech stack are you strongest in?' },
      { text: 'How do you approach testing and code quality?' },
      { text: 'What is your notice period and availability to start?' },
      { text: 'What are your salary expectations for this role?' },
    ],
    MAX_GENERATED,
  )
}

const seededJobPostings: JobPostingOut[] = [
  {
    id: 1,
    title: 'Senior Backend Engineer',
    domain: 'screening',
    description:
      'Senior Backend Engineer. We run Python/FastAPI services on Kubernetes at scale, ' +
      'with PostgreSQL and an on-call rotation. Looking for strong distributed-systems fundamentals.',
    questions: normalizeQuestions(
      [
        { text: 'How many years have you worked with Python and FastAPI?', slot: 'years_python' },
        { text: 'Describe your experience running services on Kubernetes.', slot: 'k8s_experience' },
        { text: 'Are you comfortable with a weekly on-call rotation?', slot: 'on_call' },
        { text: 'What is your notice period?', slot: 'notice_period' },
        { text: 'What are your salary expectations?', slot: 'salary_expectation' },
      ],
      MAX_CURATED,
    ),
    status: 'confirmed',
    created_at: iso(30),
    updated_at: iso(28),
  },
]

let nextJobPostingId = 2

interface MockDb {
  domains: DomainOut[]
  campaigns: CampaignOut[]
  calls: MockCall[]
  jobPostings: JobPostingOut[]
}

export const db: MockDb = {
  domains: [SCREENING_DOMAIN],
  campaigns: [DEFAULT_CAMPAIGN],
  calls: seededCalls,
  jobPostings: seededJobPostings,
}

export function listJobPostings(): JobPostingOut[] {
  return [...db.jobPostings].sort((a, b) => b.created_at.localeCompare(a.created_at))
}

export function getJobPosting(id: number): JobPostingOut | undefined {
  return db.jobPostings.find((posting) => posting.id === id)
}

export function createJobPosting(args: {
  title: string
  description: string
  domain?: string
}): JobPostingOut {
  const now = new Date().toISOString()
  const posting: JobPostingOut = {
    id: nextJobPostingId++,
    title: args.title,
    domain: args.domain ?? SCREENING_DOMAIN.name,
    description: args.description,
    questions: generateMockQuestions(args.description),
    status: 'draft',
    created_at: now,
    updated_at: now,
  }
  db.jobPostings.unshift(posting)
  return posting
}

export function deleteJobPosting(id: number): boolean {
  const index = db.jobPostings.findIndex((posting) => posting.id === id)
  if (index < 0) return false
  db.jobPostings.splice(index, 1)
  return true
}

export function updateJobPosting(
  id: number,
  patch: { title?: string; questions?: Question[]; status?: JobPostingStatus },
): JobPostingOut | undefined {
  const posting = getJobPosting(id)
  if (!posting) return undefined
  if (patch.title != null) posting.title = patch.title
  if (patch.questions != null) posting.questions = normalizeQuestions(patch.questions, MAX_CURATED)
  if (patch.status != null) posting.status = patch.status
  posting.updated_at = new Date().toISOString()
  return posting
}

function toListItem(call: MockCall): CallOut {
  return {
    call_id: call.call_id,
    campaign_id: call.campaign_id,
    domain: call.domain,
    status: call.status,
    consent_granted: call.consent_granted,
    created_at: call.created_at,
    has_notes: call.has_notes,
    has_summary: call.has_summary,
  }
}

export function listCalls(params: {
  domain?: string | null
  campaignId?: number | null
  limit: number
  offset: number
}): { items: CallOut[]; total: number } {
  const filtered = db.calls.filter((call) => {
    if (params.domain && call.domain !== params.domain) return false
    if (params.campaignId != null && call.campaign_id !== params.campaignId) return false
    return true
  })
  const items = filtered
    .slice(params.offset, params.offset + params.limit)
    .map(toListItem)
  return { items, total: filtered.length }
}

export function getCall(callId: string): MockCall | undefined {
  return db.calls.find((call) => call.call_id === callId)
}

export function upsertCall(call: MockCall): void {
  const index = db.calls.findIndex((existing) => existing.call_id === call.call_id)
  if (index >= 0) db.calls[index] = call
  else db.calls.unshift(call)
}

export function campaignByName(name: string): CampaignOut {
  return db.campaigns.find((campaign) => campaign.name === name) ?? DEFAULT_CAMPAIGN
}

export function newCallId(): string {
  return crypto.randomUUID().replace(/-/g, '')
}

export type { CallStatus }
