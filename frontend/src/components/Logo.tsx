import { clsx } from 'clsx'

/* The Omni mark: an "O" ring drawn as three converging arcs (the channels)
 * around a center node (the execution spine). Reads as an O at favicon size,
 * tells the multi-channel story at full size. Brand gradient: rose → fuchsia.
 * Keep in sync with public/favicon.svg, which embeds the same geometry. */

interface LogoMarkProps {
  /** Outer tile size in px. */
  size?: number
  className?: string
}

export function LogoMark({ size = 32, className }: LogoMarkProps) {
  return (
    <span
      className={clsx(
        'inline-flex flex-shrink-0 items-center justify-center overflow-hidden shadow-sm shadow-brand-500/30',
        className,
      )}
      style={{ width: size, height: size, borderRadius: size * 0.28 }}
    >
      <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
        <defs>
          <linearGradient id="omni-tile" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#fb7185" />
            <stop offset="55%" stopColor="#f43f5e" />
            <stop offset="100%" stopColor="#c026d3" />
          </linearGradient>
        </defs>
        <rect width="32" height="32" fill="url(#omni-tile)" />
        {/* Three arcs of the O — gaps at 12/4/8 o'clock suggest channels converging */}
        <g stroke="#fff" strokeWidth="2.6" strokeLinecap="round" fill="none">
          <path d="M 11.5 8.21 A 9 9 0 0 1 20.5 8.21" />
          <path d="M 23.79 11.5 A 9 9 0 0 1 19.6 23.25" />
          <path d="M 12.4 23.25 A 9 9 0 0 1 8.21 11.5" />
        </g>
        {/* The spine */}
        <circle cx="16" cy="16" r="2.6" fill="#fff" />
      </svg>
    </span>
  )
}

interface LogoProps {
  /** Mark size in px; the wordmark scales with it. */
  size?: number
  /** Hide the wordmark (collapsed sidebar). */
  markOnly?: boolean
  subtitle?: string
  className?: string
}

export default function Logo({ size = 32, markOnly = false, subtitle = 'Control plane', className }: LogoProps) {
  return (
    <span className={clsx('inline-flex items-center gap-2.5', className)}>
      <LogoMark size={size} />
      {!markOnly && (
        <span className="min-w-0">
          <span className="block text-sm font-bold tracking-tight text-slate-900 dark:text-white">Omni</span>
          {subtitle && (
            <span className="block text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">
              {subtitle}
            </span>
          )}
        </span>
      )}
    </span>
  )
}
