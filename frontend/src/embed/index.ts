/**
 * Public surface for embedding EchoAssist into the ACTEEK marketplace.
 *
 * ACTEEK renders the agent inside their own shell + routing + SSO:
 *
 *   import { EchoAssistAgent } from 'echoassist/embed'
 *
 *   <EchoAssistAgent
 *     config={{
 *       apiBaseUrl: 'https://api.acteek.com/echoassist',
 *       getAuthToken: () => acteekSession.accessToken,  // their SSO token
 *       domain: 'screening',
 *     }}
 *   />
 *
 * That's the whole integration. EchoAssist provides the agent workspace
 * (calls, live transcript, notes, summary, consent, metrics, domain config);
 * ACTEEK provides the marketplace, sidebar, theme, and auth.
 */
export { EchoAssistAgent, type EchoAssistAgentProps } from './EchoAssistAgent'
export type { EchoAssistConfig } from './types'
