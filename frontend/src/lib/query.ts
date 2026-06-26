import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type {
  CallDetailOut,
  CallListOut,
  CampaignOut,
  ConsentLogOut,
  DocumentUploadOut,
  DomainOut,
  HealthOut,
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
  call: (id: string) => ['calls', 'detail', id] as const,
  consent: (id: string) => ['calls', 'detail', id, 'consent'] as const,
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

export function useUploadDocument(domain: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.postForm<DocumentUploadOut>(`/domains/${domain}/documents`, form)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.domain(domain) })
    },
  })
}
