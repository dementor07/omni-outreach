import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import ErrorBoundary from './components/ErrorBoundary'
import Layout from './components/Layout'
import Login from './pages/Login'

// WORKSPACE
import Overview from './pages/Overview'
// CRM
import Contacts from './pages/Contacts'
import ContactDetail from './pages/ContactDetail'
import Companies from './pages/Companies'
import Deals from './pages/Deals'
import Leads from './pages/Leads'
// ENGAGE
import Campaigns from './pages/Campaigns'
import CampaignEditor from './pages/CampaignEditor'
import Inbox from './pages/Inbox'
import Tasks from './pages/Tasks'
import Approvals from './pages/Approvals'
// INTELLIGENCE
import Analytics from './pages/Analytics'
import ActivityPage from './pages/ActivityPage'
import AiStudio from './pages/AiStudio'
import Views from './pages/Views'
import DynamicView from './pages/DynamicView'
// SETUP
import Integrations from './pages/Integrations'
import LeadSources from './pages/LeadSources'
import Templates from './pages/Templates'
import Tones from './pages/Tones'
import Blacklist from './pages/Blacklist'
import Deliverability from './pages/Deliverability'
import Settings from './pages/Settings'

function RequireAuth() {
  const location = useLocation()
  const token = localStorage.getItem('token')
  if (!token) return <Navigate to="/login" replace state={{ from: location.pathname }} />
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
        <Route path="/" element={<Overview />} />

        {/* CRM */}
        <Route path="/contacts" element={<Contacts />} />
        <Route path="/contacts/:id" element={<ContactDetail />} />
        <Route path="/companies" element={<Companies />} />
        <Route path="/deals" element={<Deals />} />
        <Route path="/leads" element={<Leads />} />

        {/* Engage */}
        <Route path="/campaigns" element={<Campaigns />} />
        <Route path="/campaigns/:id" element={<CampaignEditor />} />
        <Route path="/inbox" element={<Inbox />} />
        <Route path="/inbox/:contactId" element={<Inbox />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/approvals" element={<Approvals />} />

        {/* Intelligence */}
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/activity" element={<ActivityPage />} />
        <Route path="/ai-studio" element={<AiStudio />} />
        <Route path="/views" element={<Views />} />
        <Route path="/views/:id" element={<DynamicView />} />

        {/* Setup */}
        <Route path="/integrations" element={<Integrations />} />
        <Route path="/lead-sources" element={<LeadSources />} />
        <Route path="/templates" element={<Templates />} />
        <Route path="/tones" element={<Tones />} />
        <Route path="/blacklist" element={<Blacklist />} />
        <Route path="/deliverability" element={<Deliverability />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" />} />
    </Routes>
  )
}
