import { useEffect, useState } from 'react'
import { Activity, ShieldAlert, CheckCircle, Clock } from 'lucide-react'

interface AuditLog {
  id: string
  timestamp: string
  verdict: string
  score: number
  reasoning: string
}

function App() {
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [stats, setStats] = useState({ total: 0, fails: 0, avgScore: 0 })

  const fetchHistory = async () => {
    try {
      const response = await fetch('/v1/history')
      const data = await response.json()
      setLogs(data.logs || [])
      
      // Calculate stats for the Bento cards
      const total = data.total_logs || 0
      const fails = data.logs?.filter((l: AuditLog) => l.verdict === 'Fail').length || 0
      const avg = data.logs?.reduce((acc: number, curr: AuditLog) => acc + curr.score, 0) / (data.logs?.length || 1)
      
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
      <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="p-6 border-b border-slate-100 flex justify-between items-center">
          <h2 className="font-semibold italic">Live Audit Stream</h2>
          <Clock size={16} className="text-slate-400" />
        </div>
        <div className="divide-y divide-slate-50">
          {logs.map((log) => (
            <div key={log.id} className="p-6 hover:bg-slate-50 transition-colors border-b border-slate-50">
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-mono text-slate-400 bg-slate-100 px-2 py-1 rounded">
                    {new Date(log.timestamp).toLocaleTimeString()}
                  </span>
                  <div className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-bold ${
                    log.verdict === 'Pass' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                  }`}>
                    {log.verdict} (Score: {log.score})
                  </div>
                </div>
                <div className="text-[10px] uppercase tracking-widest text-slate-400 font-bold">
                  Ref ID: {log.id.slice(0,8)}
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <p className="text-xs font-bold text-slate-400 uppercase mb-1">Automated Reasoning</p>
                  <p className="text-sm text-slate-600 leading-relaxed italic">
                    "{log.reasoning}"
                  </p>
                </div>

                <div className="bg-slate-50 p-3 rounded-lg border border-slate-100">
                  <p className="text-xs font-bold text-slate-400 uppercase mb-2">Technical Audit</p>
                  <div className="space-y-2">
                    <div className="flex justify-between text-xs">
                      <span>Contradiction Detected:</span>
                      <span className={log.score < 1 ? "text-red-600 font-bold" : "text-green-600"}>
                        {log.score < 1 ? "YES" : "NO"}
                      </span>
                    </div>
                    <div className="flex justify-between text-xs">
                      <span>Accuracy Threshold:</span>
                      <span>0.80</span>
                    </div>
                    <div className="w-full bg-slate-200 h-1.5 rounded-full mt-2">
                      <div
                        className={`h-1.5 rounded-full ${log.score > 0.8 ? 'bg-green-500' : 'bg-red-500'}`}
                        style={{ width: `${log.score * 100}%` }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
          {logs.length === 0 && <p className="p-10 text-center text-slate-400">No audits found in Redis.</p>}
        </div>
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