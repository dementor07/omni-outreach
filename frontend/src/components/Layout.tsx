import { Moon, Sun } from 'lucide-react'
import Sidebar from './Sidebar'
import NotificationCenter from './NotificationCenter'
import { useTheme } from '../hooks/useTheme'

interface LayoutProps {
  children: React.ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const { theme, toggle } = useTheme()

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900">
      <Sidebar />
      <main className="ml-56 min-h-screen">
        {/* Top bar */}
        <div className="sticky top-0 z-20 flex items-center justify-end gap-3 border-b border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-800/80 backdrop-blur-sm px-8 py-3">
          <button
            onClick={toggle}
            className="flex items-center justify-center rounded-lg border border-slate-200 dark:border-slate-600 p-2 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <NotificationCenter />
        </div>
        <div className="mx-auto max-w-7xl px-8 py-8">
          {children}
        </div>
      </main>
    </div>
  )
}
