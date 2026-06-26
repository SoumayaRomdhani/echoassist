import { Moon, Sun } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { Button } from './ui/button'

export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  return (
    <Button
      variant="outline"
      size="icon"
      onClick={toggle}
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
      title="Toggle theme"
    >
      {theme === 'dark' ? <Sun /> : <Moon />}
    </Button>
  )
}
