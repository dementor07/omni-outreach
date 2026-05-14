import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import ErrorBoundary from './components/ErrorBoundary'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Campaigns from './pages/Campaigns'
import Leads from './pages/Leads'
import Queue from './pages/Queue'
import Settings from './pages/Settings'
import Login from './pages/Login'
import JobSearch from './pages/JobSearch'
import LeadSources from './pages/LeadSources'
import Activity from './pages/Activity'
import Blacklist from './pages/Blacklist'
import Analytics from './pages/Analytics'
import Templates from './pages/Templates'
import Inbox from './pages/Inbox'
import Approvals from './pages/Approvals'
import StyleGuide from './pages/StyleGuide'
import RetellFlowEditor from './pages/RetellFlowEditor'

function RequireAuth() {
  const location = useLocation()
  const token = localStorage.getItem('token')

  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return (
    <Layout>
      <ErrorBoundary>
        <Outlet />
      </ErrorBoundary>
    </Layout>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/campaigns" element={<Campaigns />} />
        <Route path="/campaigns/:id" element={<Campaigns />} />
        <Route path="/campaigns/:id/voice-flow/:agentId" element={<RetellFlowEditor />} />
        <Route path="/leads" element={<Leads />} />
        <Route path="/queue" element={<Queue />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/job-search" element={<JobSearch />} />
        <Route path="/lead-sources" element={<LeadSources />} />
        <Route path="/activity" element={<Activity />} />
        <Route path="/blacklist" element={<Blacklist />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/templates" element={<Templates />} />
        <Route path="/inbox" element={<Inbox />} />
        <Route path="/approvals" element={<Approvals />} />
        <Route path="/style-guide" element={<StyleGuide />} />
      </Route>
      <Route path="*" element={<Navigate to="/" />} />
    </Routes>
  )
}
