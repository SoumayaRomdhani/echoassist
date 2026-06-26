import { useEffect, useState } from 'react'
import { Toaster as SonnerToaster } from 'sonner'

/** Track the host's theme from the `data-theme` attribute (works with or without
 *  the demo ThemeProvider — ACTEEK sets the attribute in embedded mode). */
function useDocumentTheme(): 'light' | 'dark' {
  const read = (): 'light' | 'dark' =>
    typeof document !== 'undefined' && document.documentElement.dataset.theme === 'light'
      ? 'light'
      : 'dark'
  const [theme, setTheme] = useState<'light' | 'dark'>(read)

  useEffect(() => {
    const root = document.documentElement
    const observer = new MutationObserver(() => setTheme(read()))
    observer.observe(root, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  return theme
}

export function Toaster() {
  const theme = useDocumentTheme()
  return (
    <SonnerToaster
      theme={theme}
      position="bottom-right"
      richColors
      closeButton
      toastOptions={{
        classNames: { toast: 'rounded-xl border bg-surface text-foreground' },
      }}
    />
  )
}
