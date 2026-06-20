/**
 * 任务 P0-4：文档版本对比 Modal
 *
 * - 左侧：版本列表（点击选 v1，按住 Shift 点 v2）
 * - 右侧：unified diff 渲染（绿+红）
 * - 顶部：版本元数据 + 回滚按钮
 */
import { useEffect, useState, useCallback } from 'react'
import { X, History, GitCompare, RotateCcw, Loader2, AlertCircle } from 'lucide-react'
import api from '../services/api'

interface VersionMeta {
  version: number
  doc_id: string
  title: string
  changed_by: string
  change_note: string
  created_at: string
  content_size: number
}

interface DiffResult {
  doc_id: string
  from_version: number
  to_version: number
  from_meta: Record<string, any>
  to_meta: Record<string, any>
  metadata_changes: Record<string, any>
  unified_diff: string
  diff_stats: { from_lines: number; to_lines: number; additions: number; deletions: number }
}

interface Props {
  docId: string
  open: boolean
  onClose: () => void
  onRolledBack?: () => void
}

function parseDiffLines(unified: string) {
  // 拆分行，并打 tag
  return unified.split('\n').map((line, idx) => {
    let cls = 'text-gray-600'
    let prefix = ' '
    if (line.startsWith('+++') || line.startsWith('---')) {
      cls = 'text-blue-600 font-semibold'
      prefix = ''
    } else if (line.startsWith('+')) {
      cls = 'text-green-700 bg-green-50'
      prefix = '+'
    } else if (line.startsWith('-')) {
      cls = 'text-red-700 bg-red-50'
      prefix = '-'
    } else if (line.startsWith('@@')) {
      cls = 'text-cyan-600'
      prefix = ''
    }
    return { key: idx, content: line, cls, prefix }
  })
}

export default function DocumentVersionModal({ docId, open, onClose, onRolledBack }: Props) {
  const [versions, setVersions] = useState<VersionMeta[]>([])
  const [loading, setLoading] = useState(false)
  const [fromV, setFromV] = useState<number | null>(null)
  const [toV, setToV] = useState<number | null>(null)
  const [diff, setDiff] = useState<DiffResult | null>(null)
  const [diffLoading, setDiffLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rollbackLoading, setRollbackLoading] = useState(false)

  const load = useCallback(async () => {
    if (!docId || !open) return
    setLoading(true)
    setError(null)
    try {
      const r = await api.get(`/api/documents/${docId}/versions`)
      setVersions(r.data.versions || [])
      // 默认选最后两个
      const vs = r.data.versions || []
      if (vs.length >= 2) {
        setFromV(vs[vs.length - 2].version)
        setToV(vs[vs.length - 1].version)
      } else if (vs.length === 1) {
        setFromV(vs[0].version)
        setToV(vs[0].version)
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || '加载版本失败')
    } finally {
      setLoading(false)
    }
  }, [docId, open])

  useEffect(() => { load() }, [load])

  // 拉取 diff
  useEffect(() => {
    if (!fromV || !toV || fromV === toV) {
      setDiff(null)
      return
    }
    const fetchDiff = async () => {
      setDiffLoading(true)
      setError(null)
      try {
        const r = await api.get(`/api/documents/${docId}/diff`, {
          params: { from_v: fromV, to_v: toV }
        })
        setDiff(r.data)
      } catch (e: any) {
        setDiff(null)
        setError(e?.response?.data?.detail || 'Diff 加载失败')
      } finally {
        setDiffLoading(false)
      }
    }
    fetchDiff()
  }, [docId, fromV, toV])

  const handleRollback = async (v: number) => {
    if (!confirm(`确认回滚到 v${v}？这会创建一个新版本。`)) return
    setRollbackLoading(true)
    try {
      await api.post(`/api/documents/${docId}/versions/${v}/rollback`)
      await load()
      onRolledBack?.()
    } catch (e: any) {
      setError(e?.response?.data?.detail || '回滚失败')
    } finally {
      setRollbackLoading(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-6xl max-h-[90vh] flex flex-col">
        {/* 头部 */}
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <History className="h-5 w-5 text-blue-600" />
            <h2 className="text-lg font-semibold text-gray-900">版本历史</h2>
            <span className="text-xs text-gray-500 ml-2">doc: {docId}</span>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100">
            <X className="h-5 w-5 text-gray-500" />
          </button>
        </div>

        <div className="flex-1 flex overflow-hidden">
          {/* 左侧：版本列表 */}
          <div className="w-72 border-r border-gray-100 overflow-y-auto">
            {loading ? (
              <div className="p-6 flex items-center justify-center text-gray-400 text-sm">
                <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载中
              </div>
            ) : versions.length === 0 ? (
              <div className="p-6 text-center text-gray-400 text-sm">
                <History className="h-8 w-8 mx-auto mb-2 opacity-40" />
                暂无版本记录
              </div>
            ) : (
              <div className="p-2 space-y-1">
                {[...versions].reverse().map(v => {
                  const isFrom = v.version === fromV
                  const isTo = v.version === toV
                  return (
                    <button
                      key={v.version}
                      onClick={() => {
                        if (fromV === null) setFromV(v.version)
                        else if (toV === null) setToV(v.version)
                        else { setFromV(v.version); setToV(null) }
                      }}
                      className={`w-full text-left p-3 rounded-lg border transition-colors ${
                        isFrom ? 'border-red-200 bg-red-50' :
                        isTo ? 'border-green-200 bg-green-50' :
                        'border-transparent hover:bg-gray-50'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm font-semibold text-gray-900">v{v.version}</span>
                        <span className="text-xs text-gray-400">{v.content_size}B</span>
                      </div>
                      <div className="text-xs text-gray-600 truncate">{v.title || '(无标题)'}</div>
                      <div className="text-xs text-gray-400 mt-1 flex items-center gap-2">
                        <span>{v.changed_by || 'unknown'}</span>
                        <span>{v.created_at?.slice(0, 10)}</span>
                      </div>
                      {v.change_note && (
                        <div className="text-xs text-blue-600 mt-1 truncate">{v.change_note}</div>
                      )}
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* 右侧：diff 渲染 */}
          <div className="flex-1 overflow-y-auto">
            {error && (
              <div className="m-4 px-3 py-2 rounded-lg bg-red-50 border border-red-100 text-sm text-red-700 flex items-center gap-2">
                <AlertCircle className="h-4 w-4" /> {error}
              </div>
            )}
            {!fromV || !toV ? (
              <div className="p-12 text-center text-gray-400 text-sm">
                <GitCompare className="h-10 w-10 mx-auto mb-3 opacity-40" />
                请在左侧选择两个版本进行对比
              </div>
            ) : fromV === toV ? (
              <div className="p-12 text-center text-gray-400 text-sm">
                同一版本，无需对比
              </div>
            ) : diffLoading ? (
              <div className="p-12 flex items-center justify-center text-gray-400 text-sm">
                <Loader2 className="h-4 w-4 animate-spin mr-2" /> 正在计算 diff...
              </div>
            ) : diff ? (
              <div className="p-4 space-y-3">
                {/* diff 摘要 */}
                <div className="flex items-center gap-3 text-sm">
                  <span className="px-2 py-0.5 rounded bg-red-100 text-red-700">v{diff.from_version}</span>
                  <GitCompare className="h-4 w-4 text-gray-400" />
                  <span className="px-2 py-0.5 rounded bg-green-100 text-green-700">v{diff.to_version}</span>
                  <span className="text-gray-500 ml-auto">
                    <span className="text-green-600">+{diff.diff_stats.additions}</span>
                    {' / '}
                    <span className="text-red-600">-{diff.diff_stats.deletions}</span>
                    {' / '}
                    {diff.diff_stats.from_lines} → {diff.diff_stats.to_lines} 行
                  </span>
                  <button
                    onClick={() => handleRollback(diff.from_version)}
                    disabled={rollbackLoading}
                    className="ml-3 px-3 py-1 text-xs rounded-lg bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100 disabled:opacity-50 flex items-center gap-1"
                    title="回滚到 v{diff.from_version}"
                  >
                    <RotateCcw className="h-3 w-3" />
                    回滚到 v{diff.from_version}
                  </button>
                </div>
                {/* 元数据变更 */}
                {Object.keys(diff.metadata_changes).length > 0 && (
                  <div className="px-3 py-2 rounded-lg bg-amber-50 border border-amber-100 text-xs">
                    <div className="font-semibold text-amber-700 mb-1">元数据变更</div>
                    {Object.entries(diff.metadata_changes).map(([k, v]) => (
                      <div key={k} className="text-amber-800">
                        <strong>{k}</strong>: {String((v as any).from ?? '∅')} → {String((v as any).to ?? '∅')}
                      </div>
                    ))}
                  </div>
                )}
                {/* diff 内容 */}
                <pre className="font-mono text-xs leading-relaxed border border-gray-100 rounded-lg overflow-x-auto">
                  {parseDiffLines(diff.unified_diff).map(l => (
                    <div key={l.key} className={`px-3 ${l.cls}`}>
                      {l.prefix && <span className="select-none mr-2 opacity-60">{l.prefix}</span>}
                      {l.content}
                    </div>
                  ))}
                  {diff.unified_diff === '' && (
                    <div className="p-3 text-gray-400">无内容差异</div>
                  )}
                </pre>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}
