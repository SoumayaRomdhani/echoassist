import { Brain, Ear, Loader2, Mic, Volume2, type LucideIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { cn } from '@/lib/cn'
import type { AgentState } from '@/lib/types'

/**
 * The ambient agent indicator — a layered orb that conveys the call's current
 * phase at a glance (the pattern OpenAI / ElevenLabs / LiveKit converge on).
 *
 * Colour + motion encode the state; a `volume` (0–1) modulates the pulse so the
 * orb reacts to the agent's voice. When no real amplitude is streamed, the caller
 * passes `volume={null}` and a gentle synthesized breathing drives it instead —
 * visually identical for a demo, far cheaper than streaming audio levels.
 *
 * Accessibility: state is never colour-only. The phase is announced via an
 * `aria-live` label in {@link LiveCallStage}, and `prefers-reduced-motion` drops
 * the animation to a still, legible orb.
 */

interface OrbVisual {
  /** CSS colour token driving the fill + glow. */
  color: string
  /** Baseline pulse depth (0–1) before volume is layered on. */
  intensity: number
  /** Seconds per breath — faster when speaking, slow and calm when idle. */
  period: number
}

const VISUALS: Record<AgentState, OrbVisual> = {
  idle: { color: 'var(--c-text-muted)', intensity: 0.12, period: 4.5 },
  listening: { color: 'var(--c-accent)', intensity: 0.35, period: 2.6 },
  thinking: { color: 'var(--c-accent-2)', intensity: 0.22, period: 3.2 },
  speaking: { color: 'var(--c-accent)', intensity: 0.6, period: 1.5 },
}

const ICONS: Record<AgentState, LucideIcon> = {
  idle: Mic,
  listening: Ear,
  thinking: Brain,
  speaking: Volume2,
}

const SIZE = 176 // px — the orb's bounding box

export function AgentOrb({
  state,
  volume,
  className,
}: {
  state: AgentState
  volume: number | null
  className?: string
}) {
  const visual = VISUALS[state]
  const Icon = state === 'thinking' ? Loader2 : ICONS[state]

  // Drive the pulse on a single rAF loop (not React state) so 60fps animation
  // never triggers re-renders. Volume, when streamed, is smoothed toward its
  // target; without it we synthesize a slow sine so the orb always feels alive.
  const coreRef = useRef<HTMLDivElement>(null)
  const ring1Ref = useRef<HTMLDivElement>(null)
  const ring2Ref = useRef<HTMLDivElement>(null)
  const targetVol = useRef(0)
  const smoothVol = useRef(0)
  const intensity = useRef(visual.intensity)
  const period = useRef(visual.period)

  useEffect(() => {
    intensity.current = visual.intensity
    period.current = visual.period
  }, [visual.intensity, visual.period])

  useEffect(() => {
    targetVol.current = volume == null ? 0 : Math.max(0, Math.min(1, volume))
  }, [volume])

  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      for (const ref of [coreRef, ring1Ref, ring2Ref]) {
        if (ref.current) ref.current.style.transform = 'scale(1)'
      }
      return
    }

    let raf = 0
    const start = performance.now()
    const tick = (now: number) => {
      const t = (now - start) / 1000
      // Ease streamed volume toward its target; fall back to a breathing sine.
      smoothVol.current += (targetVol.current - smoothVol.current) * 0.15
      const breath = (Math.sin((t / period.current) * Math.PI * 2) + 1) / 2
      const drive = Math.max(smoothVol.current, breath * intensity.current)

      const core = coreRef.current
      const r1 = ring1Ref.current
      const r2 = ring2Ref.current
      if (core) core.style.transform = `scale(${(1 + drive * 0.18).toFixed(4)})`
      if (r1) r1.style.transform = `scale(${(1 + drive * 0.34).toFixed(4)})`
      if (r2) r2.style.transform = `scale(${(1 + drive * 0.52).toFixed(4)})`
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])

  return (
    <div
      className={cn('relative grid place-items-center', className)}
      style={{ width: SIZE, height: SIZE }}
      aria-hidden="true"
    >
      <div
        ref={ring2Ref}
        className="absolute rounded-full transition-colors duration-500"
        style={{ width: SIZE, height: SIZE, background: visual.color, opacity: 0.1 }}
      />
      <div
        ref={ring1Ref}
        className="absolute rounded-full transition-colors duration-500"
        style={{ width: SIZE * 0.68, height: SIZE * 0.68, background: visual.color, opacity: 0.18 }}
      />
      <div
        ref={coreRef}
        className="absolute grid place-items-center rounded-full transition-colors duration-500"
        style={{
          width: SIZE * 0.42,
          height: SIZE * 0.42,
          background: visual.color,
          boxShadow: `0 0 44px 4px color-mix(in oklab, ${visual.color} 55%, transparent)`,
        }}
      >
        <Icon
          className={cn('size-7 text-background', state === 'thinking' && 'animate-spin')}
          strokeWidth={2}
        />
      </div>
    </div>
  )
}
