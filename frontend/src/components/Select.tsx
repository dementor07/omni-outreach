import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { clsx } from 'clsx'
import { Check, ChevronDown } from 'lucide-react'

// A fully themed select. Native <select> can't style its <option> panel (the OS
// owns it), which is why the app's dropdowns looked off-theme — especially in
// dark mode. This renders a button + a floating, theme-matched listbox panel so
// the whole control obeys the design system. Keyboard + outside-click + portal
// (so it escapes overflow:hidden containers) included.

export interface SelectOption {
  value: string
  label: string
  hint?: string
}

interface SelectProps {
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
  placeholder?: string
  size?: 'sm' | 'md'
  disabled?: boolean
  className?: string
  ariaLabel?: string
}

export default function Select({
  value,
  onChange,
  options,
  placeholder = 'Select…',
  size = 'md',
  disabled,
  className = '',
  ariaLabel,
}: SelectProps) {
  const [open, setOpen] = useState(false)
  const [coords, setCoords] = useState<{ left: number; top: number; width: number } | null>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const listboxId = useId()

  const selected = options.find((o) => o.value === value)
  const h = size === 'sm' ? 'h-8 text-xs px-2.5' : 'h-9 text-sm px-3'

  function place() {
    const r = btnRef.current?.getBoundingClientRect()
    if (r) setCoords({ left: r.left, top: r.bottom + 4, width: r.width })
  }

  useEffect(() => {
    if (!open) return
    place()
    function onDocClick(e: MouseEvent) {
      const t = e.target as Node
      if (!btnRef.current?.contains(t) && !panelRef.current?.contains(t)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    function onScroll() {
      place()
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
    }
  }, [open])

  function choose(v: string) {
    onChange(v)
    setOpen(false)
  }

  return (
    <div className={clsx('relative', className, disabled && 'pointer-events-none opacity-60')}>
      <button
        ref={btnRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className={clsx(
          'flex w-full items-center justify-between gap-2 rounded-lg border bg-white font-medium text-slate-700 outline-none transition-colors',
          'hover:border-slate-300 focus:border-brand-400 focus:ring-2 focus:ring-brand-100',
          'dark:bg-slate-900 dark:text-slate-200 dark:hover:border-slate-600',
          open ? 'border-brand-400 ring-2 ring-brand-100 dark:ring-brand-900/40' : 'border-slate-200 dark:border-slate-700',
          h,
        )}
      >
        <span className={clsx('truncate', !selected && 'text-slate-400')}>
          {selected ? selected.label : placeholder}
        </span>
        <ChevronDown
          size={14}
          className={clsx('shrink-0 text-slate-400 transition-transform duration-200', open && 'rotate-180')}
        />
      </button>

      {open && coords &&
        createPortal(
          <div
            ref={panelRef}
            role="listbox"
            id={listboxId}
            style={{ position: 'fixed', left: coords.left, top: coords.top, width: coords.width, zIndex: 80 }}
            className="max-h-64 overflow-auto rounded-xl border border-slate-200 bg-white p-1 shadow-xl ring-1 ring-black/5 animate-in fade-in slide-in-from-top-1 duration-150 dark:border-slate-700 dark:bg-slate-900 dark:ring-white/10"
          >
            {options.map((o) => {
              const active = o.value === value
              return (
                <button
                  key={o.value}
                  type="button"
                  role="option"
                  aria-selected={active}
                  onClick={() => choose(o.value)}
                  className={clsx(
                    'flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors',
                    active
                      ? 'bg-brand-50 font-semibold text-brand-700 dark:bg-brand-900/30 dark:text-brand-200'
                      : 'text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800',
                  )}
                >
                  <span className="min-w-0">
                    <span className="block truncate">{o.label}</span>
                    {o.hint && <span className="block truncate text-xs font-normal text-slate-400">{o.hint}</span>}
                  </span>
                  {active && <Check size={14} className="shrink-0 text-brand-600 dark:text-brand-300" />}
                </button>
              )
            })}
          </div>,
          document.body,
        )}
    </div>
  )
}
