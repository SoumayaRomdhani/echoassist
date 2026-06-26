import { setupWorker } from 'msw/browser'
import { handlers } from './handlers'

/** The in-browser mock backend (Service Worker), started from main.tsx when VITE_USE_MOCKS is on. */
export const worker = setupWorker(...handlers)
