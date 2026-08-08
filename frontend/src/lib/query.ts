import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type {
  CallDetailOut,
  CallListOut,
  CallOut,
  CampaignOut,
  ConsentLogOut,
  DocumentDeleteOut,
  DocumentListOut,
  DocumentUploadOut,
  DomainOut,
  DomainReindexOut,
  HealthOut,
  JobPostingCreate,
  JobPostingOut,
  JobPostingUpdate,
  SearchPreviewOut,
  StartCallRequest,
  StartCallResponse,
} from './types'

export interface CallsParams {
  domain?: string
  campaignId?: number
  limit?: number
  offset?: number
}

export const queryKeys = {
  ready: ['ready'] as const,
  domains: ['domains'] as const,
  domain: (domain: string) => ['domains', domain] as const,
  campaigns: ['campaigns'] as const,
  calls: (params: CallsParams) => ['calls', 'list', params] as const,
  liveCalls: (domain: string) => ['calls', 'live', domain] as const,
  call: (id: string) => ['calls', 'detail', id] as const,
  consent: (id: string) => ['calls', 'detail', id, 'consent'] as const,
  documents: (domain: string) => ['domains', domain, 'documents'] as const,
  jobPostings: ['jobPostings'] as const,
  jobPosting: (id: number) => ['jobPostings', id] as const,
}

function callsQueryString(params: CallsParams): string {
  const search = new URLSearchParams()
  if (params.domain) search.set('domain', params.domain)
  if (params.campaignId != null) search.set('campaign_id', String(params.campaignId))
  search.set('limit', String(params.limit ?? 50))
  search.set('offset', String(params.offset ?? 0))
  return search.toString()
}

export function useReady() {
  return useQuery({
    queryKey: queryKeys.ready,
    queryFn: () => api.get<HealthOut>('/ready'),
    refetchInterval: 30_000,
    retry: false,
  })
}

export function useDomains() {
  return useQuery({ queryKey: queryKeys.domains, queryFn: () => api.get<DomainOut[]>('/domains') })
}

export function useDomain(domain: string) {
  return useQuery({
    queryKey: queryKeys.domain(domain),
    queryFn: () => api.get<DomainOut>(`/domains/${domain}`),
    enabled: domain.length > 0,
  })
}

export function useCampaigns() {
  return useQuery({
    queryKey: queryKeys.campaigns,
    queryFn: () => api.get<CampaignOut[]>('/campaigns'),
  })
}

export function useCalls(params: CallsParams) {
  return useQuery({
    queryKey: queryKeys.calls(params),
    queryFn: () => api.get<CallListOut>(`/calls?${callsQueryString(params)}`),
  })
}

/**
 * Calls running right now (mic/LiveKit or server-started), polled so the live
 * banner appears within seconds of a call starting. Returns `[]` when idle.
 */
export function useLiveCalls(domain: string) {
  return useQuery({
    queryKey: queryKeys.liveCalls(domain),
    queryFn: () => api.get<CallOut[]>(`/calls/live?domain=${encodeURIComponent(domain)}`),
    enabled: domain.length > 0,
    refetchInterval: 4000,
    retry: false,
  })
}

export function useCall(id: string, options?: { refetchInterval?: number | false }) {
  return useQuery({
    queryKey: queryKeys.call(id),
    queryFn: () => api.get<CallDetailOut>(`/calls/${id}`),
    enabled: id.length > 0,
    retry: false,
    refetchInterval: options?.refetchInterval ?? false,
  })
}

export function useConsentLog(id: string) {
  return useQuery({
    queryKey: queryKeys.consent(id),
    queryFn: () => api.get<ConsentLogOut[]>(`/calls/${id}/consent`),
    enabled: id.length > 0,
    retry: false,
  })
}

export function useStartCall() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: StartCallRequest) => api.postJson<StartCallResponse>('/calls', body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['calls'] })
    },
  })
}

// --- Job postings (JD-based interviews) ----------------------------------- //
export function useJobPostings() {
  return useQuery({
    queryKey: queryKeys.jobPostings,
    queryFn: () => api.get<JobPostingOut[]>('/job-postings'),
  })
}

export function useJobPosting(id: number | null) {
  return useQuery({
    queryKey: queryKeys.jobPosting(id ?? 0),
    queryFn: () => api.get<JobPostingOut>(`/job-postings/${id}`),
    enabled: id != null,
  })
}

/** Generate a draft posting (questions drafted from the description by the LLM). */
export function useCreateJobPosting() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: JobPostingCreate) => api.postJson<JobPostingOut>('/job-postings', body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobPostings })
    },
  })
}

/** Save recruiter edits (curate questions / confirm the posting). */
export function useUpdateJobPosting(id: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: JobPostingUpdate) =>
      api.patchJson<JobPostingOut>(`/job-postings/${id}`, body),
    onSuccess: (posting) => {
      queryClient.setQueryData(queryKeys.jobPosting(id), posting)
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobPostings })
    },
  })
}

function refreshDomainDocuments(queryClient: ReturnType<typeof useQueryClient>, domain: string) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.domain(domain) })
  void queryClient.invalidateQueries({ queryKey: queryKeys.documents(domain) })
}

export function useDocuments(domain: string) {
  return useQuery({
    queryKey: queryKeys.documents(domain),
    queryFn: () => api.get<DocumentListOut>(`/domains/${domain}/documents`),
    enabled: domain.length > 0,
  })
}

export function useUploadDocument(domain: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.postForm<DocumentUploadOut>(`/domains/${domain}/documents`, form)
    },
    onSuccess: () => refreshDomainDocuments(queryClient, domain),
  })
}

export function useDeleteDocument(domain: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (source: string) =>
      api.del<DocumentDeleteOut>(
        `/domains/${domain}/documents/${source.split('/').map(encodeURIComponent).join('/')}`,
      ),
    onSuccess: () => refreshDomainDocuments(queryClient, domain),
  })
}

export function useReindexDomain(domain: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.postJson<DomainReindexOut>(`/domains/${domain}/reindex`, {}),
    onSuccess: () => refreshDomainDocuments(queryClient, domain),
  })
}

export function useSearchPreview(domain: string) {
  return useMutation({
    mutationFn: (query: string) =>
      api.postJson<SearchPreviewOut>(`/domains/${domain}/search`, { query, limit: 6 }),
  })
}
