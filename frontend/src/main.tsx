import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { AuthProvider } from './auth/AuthProvider'
import { Toaster } from './components/ui/sonner'
import { ThemeProvider } from './hooks/useTheme'
import { env } from './lib/env'
import './styles/index.css'

// Standalone dev host. <EchoAssistAgent> brings its own data/tooltip providers;
// here we add the theme + auth host and a single toast outlet, then start the
// mock backend so the app runs without a real API.
async function enableMocking(): Promise<void> {
  if (!env.useMocks) return
  const { worker } = await import('./mocks/browser')
  await worker.start({ onUnhandledRequest: 'bypass' })
}

void enableMocking().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <ThemeProvider>
        <AuthProvider>
          <App />
          <Toaster />
        </AuthProvider>
      </ThemeProvider>
    </StrictMode>,
  )
})
