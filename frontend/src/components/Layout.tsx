import { useState } from 'react'
import Sidebar from './Sidebar'
import Topbar from './Topbar'

interface LayoutProps {
  children: React.ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className="min-h-screen">
      <div className="flex">
        <div className="sticky top-0 self-start">
          <Sidebar collapsed={collapsed} />
        </div>
        <main className="min-w-0 flex-1">
          <Topbar onToggleSidebar={() => setCollapsed((c) => !c)} />
          <div className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}
