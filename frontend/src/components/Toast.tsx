import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, XCircle, X } from 'lucide-react'
import { clsx } from 'clsx'

type ToastType = 'success' | 'error'

interface Toast {
  id: number
  type: ToastType
  message: string
}

interface ToastContextValue {
  success: (message: string) => void
  error: (message: string) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

let counter = 0

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const add = useCallback((type: ToastType, message: string) => {
    const id = ++counter
    setToasts((prev) => [...prev.slice(-4), { id, type, message }])
    const timer = setTimeout(() => dismiss(id), 4000)
    timers.current.set(id, timer)
  }, [dismiss])

  useEffect(() => {
    const map = timers.current
    return () => { map.forEach(clearTimeout) }
  }, [])

  const value = useMemo(
    () => ({ success: (m: string) => add('success', m), error: (m: string) => add('error', m) }),
    [add]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Two live regions, not one. A failure needs to interrupt whatever the
          screen reader is currently saying; a success does not and should wait
          its turn. That is exactly the assertive/polite split, and it cannot be
          expressed on a single shared container — politeness is a property of
          the region, so a lone region would force one setting on both kinds.

          Both regions stay mounted even when empty. A live region only announces
          content that arrives while it is already in the accessibility tree; a
          container mounted at the same moment as its first toast is typically
          announced late or not at all.

          pointer-events-none on the wrappers, auto on each toast: the stack is
          320px wide and fixed to the bottom-right, so without this the column
          and the gaps between toasts swallow clicks meant for the page beneath. */}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[100] flex w-80 flex-col gap-2 pb-[env(safe-area-inset-bottom)] pr-[env(safe-area-inset-right)]">
        <ToastRegion toasts={toasts.filter((t) => t.type === 'error')} onDismiss={dismiss} politeness="assertive" />
        <ToastRegion toasts={toasts.filter((t) => t.type === 'success')} onDismiss={dismiss} politeness="polite" />
      </div>
    </ToastContext.Provider>
  )
}

function ToastRegion({
  toasts,
  onDismiss,
  politeness,
}: {
  toasts: Toast[]
  onDismiss: (id: number) => void
  politeness: 'polite' | 'assertive'
}) {
  return (
    <div
      role={politeness === 'assertive' ? 'alert' : 'status'}
      aria-live={politeness}
      aria-atomic="false"
      className="flex flex-col gap-2"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={clsx(
            'toast-in pointer-events-auto flex items-start gap-3 rounded-xl border px-4 py-3 text-sm font-medium shadow-lg',
            toast.type === 'success'
              ? 'border-emerald-200 bg-white text-emerald-800'
              : 'border-rose-200 bg-white text-rose-800',
          )}
        >
          {toast.type === 'success'
            ? <CheckCircle2 size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-emerald-500" />
            : <XCircle size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-rose-500" />
          }
          {/* The icon carries the success/error distinction visually, so it is
              restated in text for anyone who cannot see it — the message alone
              often reads identically either way ("Campaign 6 updated"). */}
          <span className="sr-only">{toast.type === 'success' ? 'Success:' : 'Error:'}</span>
          <span className="min-w-0 flex-1 break-words">{toast.message}</span>
          <button
            type="button"
            onClick={() => onDismiss(toast.id)}
            aria-label="Dismiss notification"
            className="shrink-0 rounded text-slate-400 transition-colors hover:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/50"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  )
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
