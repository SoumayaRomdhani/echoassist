import { createContext, useContext } from 'react'
import type { ResolvedConfig } from './types'

const AgentConfigContext = createContext<ResolvedConfig | null>(null)

export const AgentConfigProvider = AgentConfigContext.Provider

export function useAgentConfig(): ResolvedConfig {
  const config = useContext(AgentConfigContext)
  if (!config) throw new Error('useAgentConfig must be used within <EchoAssistAgent>')
  return config
}

/** The active interview domain (e.g. "screening"). */
export function useAgentDomain(): string {
  return useAgentConfig().domain
}
