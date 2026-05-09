import { useEffect, useState } from 'react'
import { Clock, ShieldAlert, Activity } from 'lucide-react'

interface AuditLog {
  id: string
  timestamp: string
  verdict: 'Pass' | 'Fail'
  trust_score: string | number
  reasoning: string
  context?: string
  actual_output?: string
}

interface SystemMetrics {
  total_audits: number
  avg_score: number
  hallucination_rate: number
  disagreement_rate: number
}

const MetricsBar = ({ stats }: { stats: SystemMetrics }) => {
  const avg = stats.avg_score || 0
  const total = stats.total_audits || 0
  const hallRate = stats.hallucination_rate || 0
  const diagRate = stats.disagreement_rate || 0

  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
      <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl shadow-xl">
        <p className="text-slate-400 text-[10px] font-black uppercase tracking-widest">Total Audits</p>
        <h3 className="text-3xl font-bold text-white mt-1">{total}</h3>
      </div>

      <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl shadow-xl">
        <p className="text-slate-400 text-[10px] font-black uppercase tracking-widest">Avg. Trust Score</p>
        <h3 className={`text-3xl font-bold mt-1 ${avg > 0.7 ? 'text-emerald-400' : 'text-orange-400'}`}>
          {Math.round(avg * 100)}%
        </h3>
      </div>

      <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl shadow-xl">
        <p className="text-slate-400 text-[10px] font-black uppercase tracking-widest">Hallucination Rate</p>
        <h3 className="text-3xl font-bold text-red-400 mt-1">{hallRate}%</h3>
      </div>

      <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl shadow-xl">
        <p className="text-slate-400 text-[10px] font-black uppercase tracking-widest">Judge Variance</p>
        <h3 className="text-3xl font-bold text-blue-400 mt-1">{diagRate}%</h3>
      </div>
    </div>
  )
}

export default function AuditHome() {
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [metrics, setMetrics] = useState<SystemMetrics>({
    total_audits: 0,
    avg_score: 0,
    hallucination_rate: 0,
    disagreement_rate: 0,
  })

  const fetchData = async () => {
    try {
      const [historyRes, metricsRes] = await Promise.all([fetch('/v1/history'), fetch('/v1/metrics')])

      if (historyRes.ok) {
        const data = await historyRes.json()
        setLogs(Array.isArray(data) ? data : data.logs || [])
      }

      if (metricsRes.ok) {
        const data = await metricsRes.json()
        setMetrics(data)
      }
    } catch (error) {
      console.error('Critical Sync Error:', error)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 5000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="min-h-screen bg-[#F9FAFB] p-8 text-slate-900">
      <header className="mb-10 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            log24x <span className="text-blue-600">Enterprise</span>
          </h1>
          <p className="text-slate-500 text-sm">Real-time Ground Truth Verification</p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1 bg-green-100 text-green-700 rounded-full text-xs font-medium">
          <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
          System Live
        </div>
      </header>

      <MetricsBar stats={metrics} />

      <section>
        <div className="mb-6 flex justify-between items-center">
          <h2 className="font-semibold text-slate-700 flex items-center gap-2">
            <Activity size={18} className="text-blue-500" />
            Audit Stream
          </h2>
          <div className="flex items-center gap-2 text-slate-400 text-xs">
            <Clock size={14} />
            <span>Updates every 5s</span>
          </div>
        </div>

        <div className="space-y-4">
          {logs.length > 0 ? (
            logs.map((log) => (
              <div key={log.id} className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                <div
                  className={`px-6 py-3 flex justify-between items-center border-b ${
                    log.verdict === 'Pass' ? 'bg-emerald-50/50 border-emerald-100' : 'bg-red-50/50 border-red-100'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <span
                      className={`text-[10px] font-black px-2 py-0.5 rounded uppercase ${
                        log.verdict === 'Pass' ? 'bg-emerald-200 text-emerald-800' : 'bg-red-200 text-red-800'
                      }`}
                    >
                      {log.verdict}
                    </span>
                    <span className="text-xs font-mono text-slate-400">ID: {log.id.slice(0, 8)}</span>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="text-right">
                      <p className="text-[10px] text-slate-400 uppercase font-bold">Reliability</p>
                      <p className="text-sm font-bold text-slate-700">
                        {Math.round(parseFloat(log.trust_score.toString()) * 100)}%
                      </p>
                    </div>
                  </div>
                </div>

                <div className="p-6 grid grid-cols-1 lg:grid-cols-3 gap-8">
                  <div className="space-y-2">
                    <label className="text-[10px] font-black text-slate-400 uppercase tracking-tighter">
                      Reference Context
                    </label>
                    <div className="p-4 bg-slate-50 rounded-xl border border-slate-100 text-sm text-slate-600 italic">
                      "{log.context}"
                    </div>
                  </div>

                  <div className="space-y-2">
                    <label className="text-[10px] font-black text-slate-400 uppercase tracking-tighter">AI Output</label>
                    <div
                      className={`p-4 rounded-xl border text-sm ${
                        log.verdict === 'Pass' ? 'bg-white border-slate-100' : 'bg-red-50 border-red-100 text-red-900'
                      }`}
                    >
                      {log.actual_output}
                    </div>
                  </div>

                  <div className="space-y-2">
                    <label className="text-[10px] font-black text-slate-400 uppercase tracking-tighter">
                      Judge Reasoning
                    </label>
                    <p className="text-sm text-slate-500 leading-relaxed">{log.reasoning}</p>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="p-20 text-center bg-white rounded-3xl border-2 border-dashed border-slate-200">
              <ShieldAlert className="mx-auto text-slate-300 mb-4" size={48} />
              <p className="text-slate-500 font-medium">Waiting for incoming audit data...</p>
              <p className="text-slate-400 text-sm">Send a POST request to /v1/audit to begin.</p>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
