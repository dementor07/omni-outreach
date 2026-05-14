import { Component, ErrorInfo, ReactNode, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { AlertTriangle, RefreshCw, Copy, Check } from 'lucide-react'

interface FallbackProps {
  error: Error
  errorInfo: ErrorInfo | null
  resetKey: string
  onReset: () => void
}

function ErrorFallback({ error, errorInfo, resetKey, onReset }: FallbackProps) {
  const [copied, setCopied] = useState(false)

  const debugPayload = JSON.stringify(
    {
      route: resetKey,
      timestamp: new Date().toISOString(),
      userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : 'unknown',
      message: error.message,
      stack: error.stack?.split('\n').slice(0, 20),
      componentStack: errorInfo?.componentStack?.split('\n').slice(0, 20),
    },
    null,
    2,
  )

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(debugPayload)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      window.prompt('Copy this debug info:', debugPayload)
    }
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center p-8">
      <div className="w-full max-w-2xl rounded-3xl border border-rose-100 bg-white p-8 shadow-xl shadow-rose-100/40">
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-rose-50 text-rose-500">
            <AlertTriangle size={24} />
          </div>
          <div className="flex-1">
            <p className="text-xs font-black uppercase tracking-[0.18em] text-rose-500">Something broke</p>
            <h2 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">
              This page hit a render error
            </h2>
            <p className="mt-3 text-sm leading-6 text-slate-500">
              The rest of the app is still working. Use the buttons below to retry this view or copy the
              debug info if you need to file a bug.
            </p>
            <div className="mt-4 rounded-xl bg-slate-50 border border-slate-200 p-4">
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Error</p>
              <p className="mt-1 font-mono text-xs text-rose-600 break-all">{error.message}</p>
            </div>
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <button
                onClick={onReset}
                className="btn-tactile flex items-center gap-2 rounded-xl bg-slate-900 px-5 py-2.5 text-xs font-black uppercase tracking-widest text-white hover:bg-slate-800 transition"
              >
                <RefreshCw size={13} />
                Retry this view
              </button>
              <button
                onClick={handleCopy}
                className="btn-tactile flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-5 py-2.5 text-xs font-bold text-slate-600 hover:bg-slate-50 transition"
              >
                {copied ? <Check size={13} className="text-emerald-600" /> : <Copy size={13} />}
                {copied ? 'Copied' : 'Copy debug info'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

interface ErrorBoundaryInnerProps {
  children: ReactNode
  resetKey: string
  onReset: () => void
}

interface ErrorBoundaryInnerState {
  error: Error | null
  errorInfo: ErrorInfo | null
}

class ErrorBoundaryInner extends Component<ErrorBoundaryInnerProps, ErrorBoundaryInnerState> {
  state: ErrorBoundaryInnerState = { error: null, errorInfo: null }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryInnerState> {
    return { error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.setState({ errorInfo })
    if (typeof console !== 'undefined') {
      // eslint-disable-next-line no-console
      console.error('[ErrorBoundary]', error, errorInfo.componentStack)
    }
  }

  componentDidUpdate(prevProps: ErrorBoundaryInnerProps) {
    if (prevProps.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null, errorInfo: null })
    }
  }

  render() {
    if (this.state.error) {
      return (
        <ErrorFallback
          error={this.state.error}
          errorInfo={this.state.errorInfo}
          resetKey={this.props.resetKey}
          onReset={this.props.onReset}
        />
      )
    }
    return this.props.children
  }
}

export default function ErrorBoundary({ children }: { children: ReactNode }) {
  const location = useLocation()
  const [manualResetCount, setManualResetCount] = useState(0)
  const resetKey = `${location.pathname}::${manualResetCount}`

  return (
    <ErrorBoundaryInner resetKey={resetKey} onReset={() => setManualResetCount((n) => n + 1)}>
      {children}
    </ErrorBoundaryInner>
  )
}
