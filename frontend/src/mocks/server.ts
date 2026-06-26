import { setupServer } from 'msw/node'
import { handlers } from './handlers'

/** Node mock backend for Vitest (used by the API client tests). */
export const server = setupServer(...handlers)
