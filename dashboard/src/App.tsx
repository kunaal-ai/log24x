import { useEffect, useState } from 'react'
import { Activity, ShieldAlert, CheckCircle, Clock } from 'lucide-react'

interface AuditLog {
  id: string
  timestamp: string
  verdict: string
  trust_score: string
  score: number
  reasoning: string
  prompt?: string
  context?: string
  actual_output?: string
}

function App() {
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [stats, setStats] = useState({ total: 0, fails: 0, avgScore: 0 })

  const fetchHistory = async () => {
    try {
      const response = await fetch('/v1/history')
      const data = await response.json()
      const items = data.logs || []
      setLogs(items)
      
      const total = items.length
      const fails = items.filter((l: AuditLog) => l.verdict === 'Fail').length
      const avg = items.reduce((acc: number, curr: AuditLog) => acc + parseFloat(curr.trust_score || '0'), 0) / (items.length || 1)
      
      setStats({ total, fails, avgScore: Number(avg.toFixed(2)) })
    } catch (error) {
      console.error("Failed to fetch logs:", error)
    }
  }

  // Polling every 5 seconds
  useEffect(() => {
    fetchHistory()
    const interval = setInterval(fetchHistory, 5000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="min-h-screen bg-[#F9FAFB] p-8 text-slate-900">
      <header className="mb-10 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">log24x <span className="text-blue-600">Enterprise</span></h1>
          <p className="text-slate-500 text-sm">Real-time AI Hallucination Monitoring</p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1 bg-green-100 text-green-700 rounded-full text-xs font-medium">
          <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
          Gateway Online
        </div>
      </header>

      {/* Bento Grid Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <StatCard title="Total Audits" value={stats.total} icon={<Activity size={20}/>} />
        <StatCard title="Avg Trust Score" value={stats.avgScore} icon={<CheckCircle size={20}/>} />
        <StatCard title="Hallucinations" value={stats.fails} color="text-red-600" icon={<ShieldAlert size={20}/>} />
      </div>

      {/* Main Audit Feed */}
      <div>
        <div className="mb-6 flex justify-between items-center">
          <h2 className="font-semibold italic">Live Audit Stream</h2>
          <Clock size={16} className="text-slate-400" />
        </div>
        {logs.map((log) => (
          <div key={log.id} className="mb-6 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden hover:shadow-md transition-shadow">
            <div className={`px-6 py-3 flex justify-between items-center border-b ${
              log.verdict === 'Pass' ? 'bg-green-50/50 border-green-100' : 'bg-red-50/50 border-red-100'
            }`}>
              <div className="flex items-center gap-4">
                <span className={`text-xs font-bold px-2 py-1 rounded-md ${
                  log.verdict === 'Pass' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                }`}>
                  {log.verdict.toUpperCase()}
                </span>
                <span className="text-xs font-mono text-slate-400">{new Date(log.timestamp).toLocaleTimeString()}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold text-slate-700">Trust Score: {parseFloat(log.trust_score || '0') * 100}%</span>
                <div className="w-24 bg-slate-200 h-2 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${parseFloat(log.trust_score || '0') > 0.8 ? 'bg-green-500' : 'bg-red-500'}`}
                    style={{ width: `${parseFloat(log.trust_score || '0') * 100}%` }}
                  />
                </div>
              </div>
            </div>

            <div className="p-6 grid grid-cols-1 lg:grid-cols-3 gap-6">

              <div className="space-y-2">
                <p className="text-[10px] font-black text-slate-400 uppercase tracking-widest">Ground Truth (Context)</p>
                <div className="p-3 bg-slate-50 rounded-lg border border-slate-100 text-sm text-slate-600 min-h-[80px]">
                  {log.context || "No context provided"}
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-[10px] font-black text-slate-400 uppercase tracking-widest">Model Output</p>
                <div className={`p-3 rounded-lg border text-sm min-h-[80px] ${
                  log.verdict === 'Pass' ? 'bg-white border-slate-100 text-slate-600' : 'bg-red-50 border-red-100 text-red-900 font-medium'
                }`}>
                  {log.actual_output || "No output provided"}
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-[10px] font-black text-slate-400 uppercase tracking-widest">Audit Reasoning</p>
                <div className="text-sm text-slate-500 leading-relaxed italic">
                  "{log.reasoning}"
                </div>
              </div>

            </div>
          </div>
        ))}
        {logs.length === 0 && <p className="p-10 text-center text-slate-400">No audits found in Redis.</p>}
      </div>
    </div>
  )
}

function StatCard({ title, value, icon, color = "text-blue-600" }: any) {
  return (
    <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm">
      <div className={`mb-4 ${color}`}>{icon}</div>
      <p className="text-slate-500 text-sm font-medium">{title}</p>
      <h3 className="text-3xl font-bold mt-1">{value}</h3>
    </div>
  )
}

export default App