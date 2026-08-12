import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { clsx } from 'clsx'
import Sidebar from './Sidebar'
import Topbar from './Topbar'

interface LayoutProps {
  children: React.ReactNode
}

export default function Layout({ children }: LayoutProps) {
  // Desktop: collapsed/expanded. Mobile (<md): slide-out drawer.
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()

  // Close drawer on route change so taps on nav items dismiss it
  useEffect(() => { setMobileOpen(false) }, [location.pathname])

  // Lock body scroll while drawer is open
  useEffect(() => {
    if (!mobileOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [mobileOpen])

  function toggleSidebar() {
    if (typeof window !== 'undefined' && window.innerWidth < 768) {
      setMobileOpen(v => !v)
    } else {
      setCollapsed(c => !c)
    }
  }

  return (
    <div className="min-h-screen">
      <div className="flex">
        {/* Desktop sidebar (md and up) */}
        <div className="sticky top-0 hidden self-start md:block">
          <Sidebar collapsed={collapsed} />
        </div>

        {/* Mobile drawer */}
        {mobileOpen && (
          <>
            <button
              type="button"
              aria-label="Close menu"
              className="fixed inset-0 z-30 bg-slate-900/50 backdrop-blur-sm md:hidden"
              onClick={() => setMobileOpen(false)}
            />
            <div className={clsx(
              'fixed inset-y-0 left-0 z-40 w-64 shadow-2xl md:hidden',
              'transition-transform duration-200',
            )}>
              <Sidebar collapsed={false} />
            </div>
          </>
        )}

        <main className="min-w-0 flex-1 bg-slate-50/25 dark:bg-transparent">
          <Topbar onToggleSidebar={toggleSidebar} />
          {/* key on the route so the content re-mounts and the page-enter rise
              re-runs on every navigation — a single, app-wide "alive" cue. */}
          <div
            key={location.pathname}
            className="page-enter mx-auto w-full max-w-[1520px] px-3 py-4 sm:px-5 sm:py-6 lg:px-7 xl:px-8"
          >
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}
