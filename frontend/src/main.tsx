import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { ThemeProvider } from './hooks/useTheme'
import { env } from './lib/env'
import './styles/index.css'

// Standalone dev only. <EchoAssistAgent> brings its own providers (TanStack Query,
// tooltips, toasts); here we just set the theme attribute and start the mock
// backend so the agent runs without a real API.
async function enableMocking(): Promise<void> {
  if (!env.useMocks) return
  const { worker } = await import('./mocks/browser')
  await worker.start({ onUnhandledRequest: 'bypass' })
}

void enableMocking().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <ThemeProvider>
        <App />
      </ThemeProvider>
    </StrictMode>,
  )
})
