import { useEffect, useState } from 'react'
import AuditHome from './pages/AuditHome'
import FraudDashboard from './pages/FraudDashboard'

function usePathname() {
  const [path, setPath] = useState(() => window.location.pathname)

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const navigate = (to: string) => {
    if (to === window.location.pathname) return
    window.history.pushState(null, '', to)
    setPath(to)
  }

  return { path, navigate }
}

export default function App() {
  const { path, navigate } = usePathname()
  const onFraud = path.startsWith('/fraud')

  return (
    <>
      <nav className="border-b border-slate-200 bg-white px-8 py-3 flex items-center gap-6 text-sm font-semibold">
        <button
          type="button"
          className={!onFraud ? 'text-blue-600' : 'text-slate-600 hover:text-slate-900'}
          onClick={() => navigate('/')}
        >
          Ground Truth
        </button>
        <button
          type="button"
          className={onFraud ? 'text-blue-600' : 'text-slate-600 hover:text-slate-900'}
          onClick={() => navigate('/fraud')}
        >
          Fraud Intelligence
        </button>
      </nav>
      {onFraud ? <FraudDashboard /> : <AuditHome />}
    </>
  )
}
