import { useState, useRef, useEffect } from 'react'
import {
  Search, Brain, Network, FileText, Loader2, X,
  Sparkles, ChevronRight, Target, BookOpen
} from 'lucide-react'
import { searchApi } from '../services/api'
import { useKB } from '../contexts/KBContext'
import SearchProgress, { type SearchProgress as Progress } from '../components/SearchProgress'

interface SearchResult {
  vector?: any[]
  graph?: { nodes: any[]; edges: any[] }
  text?: any[]
}

// 任务 1.2：持久化辅助
const PROGRESS_KEY_PREFIX = 'search_progress:'
const RESULT_KEY_PREFIX = 'search_result:'
const getProgressKey = (q: string, kb: string) => `${PROGRESS_KEY_PREFIX}${kb}:${q}`
const getResultKey = (q: string, kb: string) => `${RESULT_KEY_PREFIX}${kb}:${q}`

export default function SearchPage() {
  const { currentKBId } = useKB()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<'vector' | 'graph' | 'text'>('vector')
  const [progress, setProgress] = useState<Progress | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  // 任务 1.2：组件挂载时恢复最近的搜索进度
  useEffect(() => {
    if (typeof window === 'undefined') return
    const recent = localStorage.getItem('search_recent')
    if (recent) {
      try {
        const { q, kb } = JSON.parse(recent)
        if (q && kb) {
          const savedProgress = localStorage.getItem(getProgressKey(q, kb))
          if (savedProgress) setProgress(JSON.parse(savedProgress))
          const savedResult = localStorage.getItem(getResultKey(q, kb))
          if (savedResult) setResults(JSON.parse(savedResult))
        }
      } catch {}
    }
    return () => {
      // 任务 1.1 关键修复：组件卸载**不**关闭 EventSource
      // 由后端流自然结束 或 用户显式 cancel 时关闭
      // eventSourceRef.current?.close()
    }
  }, [])

  // 任务 1.1：进度变化时持久化
  useEffect(() => {
    if (progress && query && currentKBId) {
      localStorage.setItem(getProgressKey(query, currentKBId), JSON.stringify(progress))
      localStorage.setItem('search_recent', JSON.stringify({ q: query, kb: currentKBId }))
    }
  }, [progress, query, currentKBId])

  const handleSearch = async () => {
    if (!query.trim()) return
    setLoading(true)
    setProgress({
      stage: 'init', label: '开始检索...', percent: 0, elapsed_ms: 0
    })

    // 关闭旧连接
    eventSourceRef.current?.close()

    // 任务 1.1：使用 EventSource 接收 SSE 流式进度
    // 关键：EventSource 是浏览器原生 API，不受 React 组件卸载影响
    const url = `/api/search/hybrid/stream?q=${encodeURIComponent(query)}&limit=10&knowledge_base_id=${currentKBId || 'all'}`
    const es = new EventSource(url)
    eventSourceRef.current = es

    es.addEventListener('progress', (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data)
        setProgress(data)
      } catch {}
    })

    es.addEventListener('done', (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data)
        setResults(data.data)
        setProgress({
          stage: 'done',
          label: `检索完成（${data.data.vector?.length || 0} 向量 + ${data.data.graph?.nodes?.length || 0} 图谱 + ${data.data.text?.length || 0} 文本）`,
          percent: 100,
          elapsed_ms: data.elapsed_ms
        })
        // 持久化最终结果
        localStorage.setItem(getResultKey(query, currentKBId || 'all'), JSON.stringify(data.data))
        setLoading(false)
        es.close()
      } catch {}
    })

    es.addEventListener('warn', (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data)
        console.warn(`[Search] ${data.stage}: ${data.message}`)
      } catch {}
    })

    es.addEventListener('error', (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data)
        setProgress({
          stage: 'error',
          label: '检索失败',
          percent: 0,
          elapsed_ms: 0,
          message: data.message
        })
      } catch {}
      setLoading(false)
      es.close()
    })

    es.onerror = () => {
      // 网络中断
      setLoading(false)
      es.close()
    }
  }

  const handleCancel = () => {
    eventSourceRef.current?.close()
    setLoading(false)
    setProgress(null)
  }

  const tabs = [
    {
      key: 'vector' as const,
      label: '语义检索',
      icon: Brain,
      count: results?.vector?.length || 0,
      color: 'text-purple-600',
      bgColor: 'bg-purple-50'
    },
    {
      key: 'graph' as const,
      label: '图谱检索',
      icon: Network,
      count: results?.graph?.nodes?.length || 0,
      color: 'text-emerald-600',
      bgColor: 'bg-emerald-50'
    },
    {
      key: 'text' as const,
      label: '关键词匹配',
      icon: FileText,
      count: results?.text?.length || 0,
      color: 'text-blue-600',
      bgColor: 'bg-blue-50'
    }
  ]

  return (
    <div className="space-y-6">
      {/* 页面标题 */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">混合检索</h1>
        <p className="text-sm text-gray-500 mt-1">语义搜索 + 知识图谱 + 关键词匹配联合检索</p>
      </div>

      {/* 搜索框 */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
        <div className="flex gap-3">
          <div className="flex-1 relative">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="输入关键词或问题..."
              className="w-full pl-12 pr-10 py-4 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 text-base"
            />
            {query && (
              <button
                onClick={() => { setQuery(''); setResults(null) }}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-full hover:bg-gray-200 transition-colors"
                title="清空搜索"
              >
                <X className="h-4 w-4 text-gray-400" />
              </button>
            )}
          </div>
          <button
            onClick={handleSearch}
            disabled={loading || !query.trim()}
            className="px-8 py-4 bg-gradient-to-r from-blue-500 to-indigo-600 text-white rounded-xl hover:shadow-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {loading ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin" />
                <span>检索中...</span>
              </>
            ) : (
              <>
                <Sparkles className="h-5 w-5" />
                <span>检索</span>
              </>
            )}
          </button>
        </div>

        {/* 快捷搜索建议 */}
        <div className="flex flex-wrap gap-2 mt-4">
          <span className="text-xs text-gray-400 flex items-center gap-1">
            <Target className="h-3 w-3" />
            试试：
          </span>
          {['RAG 技术原理', '向量数据库对比', '知识图谱构建'].map((q) => (
            <button
              key={q}
              onClick={() => { setQuery(q); handleSearch() }}
              className="px-3 py-1.5 bg-gray-50 text-gray-600 rounded-lg text-sm hover:bg-gray-100 transition-colors"
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      {/* 任务 1.2：进度条（实时同步） */}
      <SearchProgress progress={progress} visible={loading || !!progress} onCancel={handleCancel} />

      {/* 检索结果 */}
      {results && (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
          {/* Tab 切换 */}
          <div className="flex border-b border-gray-100">
            {tabs.map((tab) => {
              const Icon = tab.icon
              return (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`flex items-center gap-2 px-6 py-4 text-sm font-medium transition-colors border-b-2 ${
                    activeTab === tab.key
                      ? 'border-blue-500 text-blue-600 bg-blue-50/50'
                      : 'border-transparent text-gray-500 hover:text-gray-700'
                  }`}
                >
                  <Icon className={`h-4 w-4 ${activeTab === tab.key ? tab.color : ''}`} />
                  <span>{tab.label}</span>
                  <span className={`px-2 py-0.5 rounded-full text-xs ${tab.bgColor} ${tab.color}`}>
                    {tab.count}
                  </span>
                </button>
              )
            })}
          </div>

          <div className="p-6">
            {/* 向量检索结果 */}
            {activeTab === 'vector' && (
              <div className="space-y-4">
                {results.vector?.length === 0 ? (
                  <div className="text-center py-12 text-gray-400">
                    <Brain className="h-12 w-12 mx-auto mb-3 text-gray-200" />
                    <p>未找到语义相关结果</p>
                  </div>
                ) : (
                  results.vector?.map((item, idx) => (
                    <div
                      key={idx}
                      className="p-5 bg-gray-50/50 rounded-xl border border-gray-100 hover:border-blue-200 transition-colors"
                    >
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <div className="w-8 h-8 rounded-lg bg-purple-100 flex items-center justify-center">
                            <Brain className="h-4 w-4 text-purple-600" />
                          </div>
                          <span className="text-sm font-medium text-gray-700">语义匹配</span>
                        </div>
                        <div className="flex items-center gap-1">
                          <Target className="h-3.5 w-3.5 text-purple-500" />
                          <span className="text-sm font-semibold text-purple-600">
                            {(item.score * 100).toFixed(1)}%
                          </span>
                        </div>
                      </div>
                      <p className="text-gray-700 text-sm leading-relaxed">{item.content}</p>
                      <div className="flex items-center gap-2 mt-3 pt-3 border-t border-gray-100">
                        <BookOpen className="h-3.5 w-3.5 text-gray-400" />
                        <span className="text-xs text-gray-500">
                          来源: {item.metadata?.title || '未知文档'}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {/* 图谱检索结果 */}
            {activeTab === 'graph' && (
              <div className="space-y-4">
                {results.graph?.nodes?.length === 0 ? (
                  <div className="text-center py-12 text-gray-400">
                    <Network className="h-12 w-12 mx-auto mb-3 text-gray-200" />
                    <p>未找到相关实体</p>
                  </div>
                ) : (
                  <>
                    <div className="flex flex-wrap gap-3">
                      {results.graph?.nodes?.map((node, idx) => (
                        <div
                          key={idx}
                          className="flex items-center gap-3 px-4 py-3 bg-emerald-50 rounded-xl border border-emerald-100"
                        >
                          <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center">
                            <Network className="h-4 w-4 text-emerald-600" />
                          </div>
                          <div>
                            <p className="font-medium text-gray-900">{node.name}</p>
                            <p className="text-xs text-gray-500">{node.type}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                    
                    {results.graph?.edges && results.graph.edges.length > 0 && (
                      <div className="mt-6">
                        <h4 className="text-sm font-semibold text-gray-700 mb-3">关联关系</h4>
                        <div className="space-y-2">
                          {results.graph.edges.map((edge, idx) => (
                            <div
                              key={idx}
                              className="flex items-center gap-3 px-4 py-2.5 bg-gray-50 rounded-lg text-sm"
                            >
                              <span className="font-medium text-gray-700">{edge.source_name}</span>
                              <ChevronRight className="h-4 w-4 text-gray-400" />
                              <span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">
                                {edge.type}
                              </span>
                              <ChevronRight className="h-4 w-4 text-gray-400" />
                              <span className="font-medium text-gray-700">{edge.target_name}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {/* 关键词匹配结果 */}
            {activeTab === 'text' && (
              <div className="space-y-4">
                {results.text?.length === 0 ? (
                  <div className="text-center py-12 text-gray-400">
                    <FileText className="h-12 w-12 mx-auto mb-3 text-gray-200" />
                    <p>未找到关键词匹配</p>
                  </div>
                ) : (
                  results.text?.map((item, idx) => (
                    <div
                      key={idx}
                      className="p-5 bg-gray-50/50 rounded-xl border border-gray-100 hover:border-blue-200 transition-colors"
                    >
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center">
                            <FileText className="h-4 w-4 text-blue-600" />
                          </div>
                          <h3 className="font-medium text-gray-900">{item.document?.title || '未知文档'}</h3>
                        </div>
                        <div className="flex items-center gap-1">
                          <Target className="h-3.5 w-3.5 text-blue-500" />
                          <span className="text-sm font-semibold text-blue-600">
                            {(item.score * 100).toFixed(1)}%
                          </span>
                        </div>
                      </div>
                      <p className="text-gray-600 text-sm leading-relaxed">
                        {item.snippet || item.document?.content?.slice(0, 300)}...
                      </p>
                      <div className="flex items-center gap-2 mt-3 pt-3 border-t border-gray-100">
                        <BookOpen className="h-3.5 w-3.5 text-gray-400" />
                        <span className="text-xs text-gray-500">
                          来源: {item.document?.title || '未知文档'}
                        </span>
                        <span className="text-xs text-gray-400 ml-2">
                          分类: {item.document?.category || '默认'}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 空状态 */}
      {!results && !loading && (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-12 text-center">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-50 to-indigo-50 flex items-center justify-center mx-auto mb-4">
            <Search className="h-8 w-8 text-blue-400" />
          </div>
          <p className="text-lg font-medium text-gray-600">输入关键词开始检索</p>
          <p className="text-sm text-gray-400 mt-2">支持语义搜索、图谱检索和关键词匹配三种方式</p>
        </div>
      )}
    </div>
  )
}
