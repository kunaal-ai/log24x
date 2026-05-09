import { useCallback, useEffect, useMemo, useState } from 'react'
import { Brain, Loader2, ShieldAlert, X } from 'lucide-react'

export interface TransactionAlert {
  transaction_id: string
  account_id?: string | null
  amount_usd?: number | null
  merchant_name?: string | null
  location?: string | null
  timestamp?: string | null
  transaction_type?: string | null
  rules_triggered: string[]
  risk_score?: number | null
  risk_label?: string | null
  flagged_at?: string | null
}

export interface FraudAnalysisSummary {
  total_analyzed: number
  total_flagged: number
  by_rule: Record<string, number>
  by_risk_label: Record<string, number>
  alerts: TransactionAlert[]
}

interface FraudStats {
  total_alerts: number
  by_risk_label: Record<string, number>
  by_rule: Record<string, number>
  top_accounts: { account_id: string; alert_count: number }[]
  analysis_timestamp: string
}

interface ExplainResponse {
  transaction_id: string
  ai_explanation: string
  cached: boolean
}

const RISK_OPTIONS = ['All', 'CONFIRMED_FRAUD', 'HIGH', 'MEDIUM', 'LOW'] as const
const RULE_OPTIONS = [
  'All',
  'STRUCTURING',
  'RAPID_MOVEMENT',
  'INTL_SPIKE',
  'ROUND_AMOUNT',
  'HIGH_VELOCITY',
] as const

function riskPalette(label: string) {
  if (label === 'CONFIRMED_FRAUD' || label === 'HIGH') {
    return { bg: 'bg-red-100', text: 'text-red-800', chip: 'bg-red-600 text-white' }
  }
  if (label === 'MEDIUM') {
    return { bg: 'bg-amber-100', text: 'text-amber-900', chip: 'bg-amber-500 text-white' }
  }
  return { bg: 'bg-slate-200', text: 'text-slate-800', chip: 'bg-slate-500 text-white' }
}

function formatMoney(n: number) {
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

function UploadAnalyze(props: {
  onResult: (r: FraudAnalysisSummary) => void
  isAnalyzing: boolean
  setAnalyzing: (v: boolean) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)

  const onAnalyze = async () => {
    if (!file) return
    props.setAnalyzing(true)
    setError(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch('/fraud/analyze', { method: 'POST', body: fd })
      const text = await res.text()
      if (!res.ok) {
        let detail = text
        try {
          const j = JSON.parse(text)
          detail = j.detail ?? text
        } catch {
          /* keep text */
        }
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
      }
      const data = JSON.parse(text) as FraudAnalysisSummary
      props.onResult(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      props.setAnalyzing(false)
    }
  }

  return (
    <section className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm space-y-4">
      <div className="flex items-center gap-2">
        <ShieldAlert className="text-blue-600" size={20} />
        <h2 className="text-lg font-semibold text-slate-900">Upload and analyze</h2>
      </div>
      <p className="text-sm text-slate-600">
        Select an enriched Kaggle export (for example <span className="font-mono text-xs">creditcard_enriched.csv</span>).
        Large files may take several seconds.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="file"
          accept=".csv"
          className="text-sm"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button
          type="button"
          disabled={!file || props.isAnalyzing}
          onClick={onAnalyze}
          className="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Analyze
        </button>
        {file ? <span className="text-xs text-slate-500">{file.name}</span> : null}
      </div>
      {props.isAnalyzing ? (
        <div className="flex items-center gap-2 text-sm text-slate-700">
          <Loader2 className="animate-spin text-blue-600" size={18} />
          Analyzing transactions...
        </div>
      ) : null}
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </section>
  )
}

function StatsOverview(props: { enabled: boolean; refreshKey: string }) {
  const [stats, setStats] = useState<FraudStats | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!props.enabled) {
      setStats(null)
      return
    }
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const res = await fetch('/fraud/stats')
        if (!res.ok) return
        const data = (await res.json()) as FraudStats
        if (!cancelled) setStats(data)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [props.enabled, props.refreshKey])

  const ruleEntries = useMemo(() => {
    if (!stats) return []
    const order = ['STRUCTURING', 'RAPID_MOVEMENT', 'INTL_SPIKE', 'ROUND_AMOUNT', 'HIGH_VELOCITY']
    const max = Math.max(1, ...order.map((k) => stats.by_rule[k] ?? 0))
    return order.map((k) => ({ name: k, count: stats.by_rule[k] ?? 0, max }))
  }, [stats])

  const riskEntries = useMemo(() => {
    if (!stats) return []
    const order = ['CONFIRMED_FRAUD', 'HIGH', 'MEDIUM', 'LOW']
    return order.map((k) => ({ label: k, count: stats.by_risk_label[k] ?? 0 }))
  }, [stats])

  const donutGradient = useMemo(() => {
    const total = riskEntries.reduce((a, b) => a + b.count, 0) || 1
    let acc = 0
    const parts: string[] = []
    for (const seg of riskEntries) {
      const frac = seg.count / total
      const start = acc * 360
      acc += frac
      const end = acc * 360
      const col =
        seg.label === 'CONFIRMED_FRAUD' || seg.label === 'HIGH'
          ? '#dc2626'
          : seg.label === 'MEDIUM'
            ? '#f59e0b'
            : '#64748b'
      parts.push(`${col} ${start.toFixed(2)}deg ${end.toFixed(2)}deg`)
    }
    return `conic-gradient(${parts.join(', ')})`
  }, [riskEntries])

  if (!props.enabled) return null

  if (loading || !stats) {
    return (
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-6">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-40 rounded-2xl bg-slate-100 animate-pulse border border-slate-200" />
        ))}
      </section>
    )
  }

  return (
    <section className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="bg-white border border-slate-200 rounded-2xl p-4 shadow-sm">
        <h3 className="text-xs font-black uppercase tracking-widest text-slate-500 mb-3">Alerts by rule</h3>
        <div className="space-y-3">
          {ruleEntries.map((r) => (
            <div key={r.name}>
              <div className="flex justify-between text-xs text-slate-600 mb-1">
                <span className="font-mono">{r.name}</span>
                <span>{r.count}</span>
              </div>
              <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
                <div
                  className="h-full bg-blue-600"
                  style={{ width: `${(r.count / r.max) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-2xl p-4 shadow-sm flex flex-col items-center">
        <h3 className="text-xs font-black uppercase tracking-widest text-slate-500 mb-3 w-full">
          Alerts by risk label
        </h3>
        <div
          className="w-40 h-40 rounded-full border-4 border-white shadow-md"
          style={{ backgroundImage: donutGradient }}
        />
        <div className="mt-4 grid grid-cols-2 gap-2 w-full text-xs">
          {riskEntries.map((r) => (
            <div key={r.label} className="flex items-center justify-between gap-2 text-slate-600">
              <span className="truncate">{r.label}</span>
              <span className="font-semibold">{r.count}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-2xl p-4 shadow-sm">
        <h3 className="text-xs font-black uppercase tracking-widest text-slate-500 mb-3">Top accounts</h3>
        <ol className="space-y-2 text-sm">
          {stats.top_accounts.slice(0, 5).map((a, idx) => (
            <li key={a.account_id} className="flex justify-between border-b border-slate-100 pb-2">
              <span className="text-slate-500">
                {idx + 1}. <span className="font-mono text-slate-800">{a.account_id}</span>
              </span>
              <span className="font-semibold">{a.alert_count}</span>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

function AlertQueue(props: {
  enabled: boolean
  risk: string
  rule: string
  onRiskChange: (v: string) => void
  onRuleChange: (v: string) => void
  onSelect: (row: TransactionAlert) => void
}) {
  const [rows, setRows] = useState<TransactionAlert[]>([])
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const pageSize = 20

  const query = useMemo(() => {
    const p = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
    if (props.risk !== 'All') p.set('risk_label', props.risk)
    if (props.rule !== 'All') p.set('rule_name', props.rule)
    return p.toString()
  }, [props.risk, props.rule, page])

  const load = useCallback(async () => {
    if (!props.enabled) return
    setLoading(true)
    try {
      const res = await fetch(`/fraud/alerts?${query}`)
      if (!res.ok) {
        setRows([])
        return
      }
      const data = (await res.json()) as TransactionAlert[]
      setRows(data)
    } finally {
      setLoading(false)
    }
  }, [props.enabled, query])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    setPage(1)
  }, [props.risk, props.rule])

  if (!props.enabled) return null

  return (
    <section className="mt-6 bg-white border border-slate-200 rounded-2xl p-4 shadow-sm">
      <div className="flex flex-wrap gap-3 mb-4">
        <label className="text-xs font-bold text-slate-500 flex items-center gap-2">
          Risk
          <select
            className="border border-slate-200 rounded-lg px-2 py-1 text-sm bg-white"
            value={props.risk}
            onChange={(e) => props.onRiskChange(e.target.value)}
          >
            {RISK_OPTIONS.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-bold text-slate-500 flex items-center gap-2">
          Rule
          <select
            className="border border-slate-200 rounded-lg px-2 py-1 text-sm bg-white"
            value={props.rule}
            onChange={(e) => props.onRuleChange(e.target.value)}
          >
            {RULE_OPTIONS.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
      </div>

      {loading ? (
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-10 bg-slate-100 animate-pulse rounded-lg" />
          ))}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500 border-b">
                <th className="py-2 pr-3">Txn</th>
                <th className="py-2 pr-3">Account</th>
                <th className="py-2 pr-3">Amount</th>
                <th className="py-2 pr-3">Merchant</th>
                <th className="py-2 pr-3">Location</th>
                <th className="py-2 pr-3">Rules</th>
                <th className="py-2 pr-3">Score</th>
                <th className="py-2 pr-3">Label</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const pal = riskPalette(String(r.risk_label ?? 'LOW'))
                return (
                  <tr
                    key={r.transaction_id}
                    className="border-b border-slate-100 hover:bg-slate-50 cursor-pointer"
                    onClick={() => props.onSelect(r)}
                  >
                    <td className="py-2 pr-3 font-mono text-xs">{r.transaction_id.slice(0, 12)}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{r.account_id}</td>
                    <td className="py-2 pr-3">{formatMoney(Number(r.amount_usd ?? 0))}</td>
                    <td className="py-2 pr-3 max-w-[140px] truncate">{r.merchant_name}</td>
                    <td className="py-2 pr-3 max-w-[140px] truncate">{r.location}</td>
                    <td className="py-2 pr-3">
                      <div className="flex flex-wrap gap-1">
                        {r.rules_triggered.map((x) => (
                          <span key={x} className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-900">
                            {x}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="py-2 pr-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-bold ${pal.chip}`}>{r.risk_score}</span>
                    </td>
                    <td className="py-2 pr-3">
                      <span className={`text-xs px-2 py-0.5 rounded font-bold ${pal.bg} ${pal.text}`}>
                        {r.risk_label}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between mt-4 text-sm">
        <button
          type="button"
          className="px-3 py-1 rounded-lg border border-slate-200 disabled:opacity-40"
          disabled={page <= 1 || loading}
          onClick={() => setPage((p) => Math.max(1, p - 1))}
        >
          Previous
        </button>
        <span className="text-slate-600">Page {page}</span>
        <button
          type="button"
          className="px-3 py-1 rounded-lg border border-slate-200 disabled:opacity-40"
          disabled={loading || rows.length < pageSize}
          onClick={() => setPage((p) => p + 1)}
        >
          Next
        </button>
      </div>
    </section>
  )
}

function ExplainPanel(props: {
  row: TransactionAlert | null
  onClose: () => void
}) {
  const [data, setData] = useState<ExplainResponse | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!props.row) {
      setData(null)
      return
    }
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setData(null)
      try {
        const res = await fetch(`/fraud/alerts/${encodeURIComponent(props.row!.transaction_id)}/explain`)
        if (!res.ok) return
        const json = (await res.json()) as ExplainResponse
        if (!cancelled) setData(json)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [props.row])

  if (!props.row) return null

  const pal = riskPalette(String(props.row.risk_label ?? 'LOW'))

  return (
    <div className="fixed inset-0 z-50 flex">
      <button
        type="button"
        className="flex-1 bg-slate-900/40"
        aria-label="Close panel"
        onClick={props.onClose}
      />
      <div className="w-full max-w-md bg-white h-full shadow-2xl border-l border-slate-200 flex flex-col">
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="font-semibold text-slate-900">Alert detail</h3>
          <button type="button" onClick={props.onClose} className="p-2 rounded-lg hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>
        <div className="p-4 space-y-4 overflow-y-auto flex-1">
          <div className="rounded-xl border border-slate-200 p-4 space-y-2 text-sm">
            <div className="flex justify-between gap-2">
              <span className="text-slate-500">Transaction</span>
              <span className="font-mono text-xs text-right">{props.row.transaction_id}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-slate-500">Account</span>
              <span className="font-mono text-xs">{props.row.account_id}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-slate-500">Amount</span>
              <span className="font-semibold">{formatMoney(Number(props.row.amount_usd ?? 0))}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-slate-500">Merchant</span>
              <span className="text-right">{props.row.merchant_name}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-slate-500">Location</span>
              <span className="text-right">{props.row.location}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-slate-500">Time</span>
              <span className="text-right text-xs">{props.row.timestamp}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-slate-500">Rules</span>
              <span className="text-right text-xs">{(props.row.rules_triggered ?? []).join(', ')}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-slate-500">Score</span>
              <span className={`px-2 py-0.5 rounded text-xs font-bold ${pal.chip}`}>{props.row.risk_score}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-slate-500">Label</span>
              <span className={`text-xs px-2 py-0.5 rounded font-bold ${pal.bg} ${pal.text}`}>
                {props.row.risk_label}
              </span>
            </div>
          </div>

          <div className="rounded-xl bg-slate-50 border border-slate-200 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Brain className="text-blue-600" size={18} />
              <span className="text-sm font-semibold text-slate-900">AI Fraud Analysis</span>
              {data?.cached ? (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 font-bold">
                  Cached
                </span>
              ) : null}
            </div>
            {loading ? (
              <div className="flex items-center gap-2 text-sm text-slate-600">
                <Loader2 className="animate-spin" size={16} />
                Generating explanation...
              </div>
            ) : (
              <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">
                {data?.ai_explanation ?? '—'}
              </p>
            )}
          </div>

          <button
            type="button"
            onClick={props.onClose}
            className="w-full py-2 rounded-xl border border-slate-200 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

export default function FraudDashboard() {
  const [analysisResult, setAnalysisResult] = useState<FraudAnalysisSummary | null>(null)
  const [selectedTransaction, setSelectedTransaction] = useState<TransactionAlert | null>(null)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [risk, setRisk] = useState<string>('All')
  const [rule, setRule] = useState<string>('All')

  const enabled = analysisResult !== null
  const statsRefreshKey = analysisResult
    ? `${analysisResult.total_analyzed}-${analysisResult.total_flagged}`
    : 'idle'

  return (
    <div className="min-h-screen bg-[#F9FAFB] p-8 text-slate-900">
      <header className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">
          Fraud <span className="text-blue-600">Intelligence</span>
        </h1>
        <p className="text-slate-500 text-sm">Rule-based detection with Gemini explanations</p>
      </header>

      <UploadAnalyze
        onResult={setAnalysisResult}
        isAnalyzing={isAnalyzing}
        setAnalyzing={setIsAnalyzing}
      />

      {analysisResult ? (
        <section className="mt-6 bg-white border border-slate-200 rounded-2xl p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-800 mb-2">Analysis summary</h3>
          <p className="text-sm text-slate-600">
            Analyzed <span className="font-semibold">{analysisResult.total_analyzed}</span> transactions —{' '}
            <span className="font-semibold">{analysisResult.total_flagged}</span> alerts
          </p>
          <div className="flex flex-wrap gap-2 mt-3">
            {Object.entries(analysisResult.by_risk_label).map(([k, v]) => {
              const p = riskPalette(k)
              return (
                <span key={k} className={`text-xs px-2 py-1 rounded-full font-bold ${p.bg} ${p.text}`}>
                  {k}: {v}
                </span>
              )
            })}
          </div>
        </section>
      ) : null}

      <StatsOverview enabled={enabled} refreshKey={statsRefreshKey} />

      <AlertQueue
        enabled={enabled}
        risk={risk}
        rule={rule}
        onRiskChange={setRisk}
        onRuleChange={setRule}
        onSelect={setSelectedTransaction}
      />

      <ExplainPanel row={selectedTransaction} onClose={() => setSelectedTransaction(null)} />
    </div>
  )
}
