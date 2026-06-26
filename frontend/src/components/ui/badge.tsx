import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/cn'

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-accent/15 text-accent',
        ready: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-500',
        soon: 'border-amber-500/30 bg-amber-500/10 text-amber-500',
        muted: 'border-transparent bg-foreground/[0.06] text-muted',
        outline: 'text-foreground',
        violet: 'border-transparent bg-[var(--c-accent-2)]/15 text-[var(--c-accent-2)]',
        pink: 'border-transparent bg-[var(--c-accent-3)]/15 text-[var(--c-accent-3)]',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

export interface BadgeProps
  extends ComponentProps<'span'>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { badgeVariants }
