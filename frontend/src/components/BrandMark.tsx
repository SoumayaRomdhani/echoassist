/** EchoAssist mark — a symmetric soundwave (voice agent), cyan→violet gradient. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="echo-mark" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#4AF4FF" />
          <stop offset="1" stopColor="#7C6BFF" />
        </linearGradient>
      </defs>
      <rect x="2.5" y="13" width="3" height="6" rx="1.5" fill="url(#echo-mark)" />
      <rect x="8.5" y="9" width="3" height="14" rx="1.5" fill="url(#echo-mark)" />
      <rect x="14.5" y="4" width="3" height="24" rx="1.5" fill="url(#echo-mark)" />
      <rect x="20.5" y="9" width="3" height="14" rx="1.5" fill="url(#echo-mark)" />
      <rect x="26.5" y="13" width="3" height="6" rx="1.5" fill="url(#echo-mark)" />
    </svg>
  )
}
