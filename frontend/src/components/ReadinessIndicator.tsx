import { Activity } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { HealthOut } from '@/lib/types'
import { Badge, type BadgeProps } from './ui/badge'

/** Backend health pill driven by GET /ready, polled every 30s (no react-query needed). */
export function ReadinessIndicator() {
  const [data, setData] = useState<HealthOut | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    async function check() {
      try {
        const result = await api.get<HealthOut>('/ready')
        if (active) {
          setData(result)
          setError(false)
        }
      } catch {
        if (active) setError(true)
      } finally {
        if (active) setLoading(false)
      }
    }
    void check()
    const id = setInterval(check, 30_000)
    return () => {
      active = false
      clearInterval(id)
    }
  }, [])

  const ok = data?.status === 'ok'
  let variant: BadgeProps['variant'] = 'muted'
  let label = 'Checking…'
  if (!loading) {
    if (error) {
      variant = 'pink'
      label = 'Backend offline'
    } else if (ok) {
      variant = 'ready'
      label = 'All systems go'
    } else {
      variant = 'soon'
      label = 'Degraded'
    }
  }

  const components = data?.components ?? {}
  const title = Object.keys(components).length
    ? Object.entries(components)
        .map(([name, state]) => `${name}: ${state}`)
        .join(' · ')
    : undefined

  return (
    <span title={title}>
      <Badge variant={variant}>
        <Activity className="size-3" />
        {label}
      </Badge>
    </span>
  )
}
