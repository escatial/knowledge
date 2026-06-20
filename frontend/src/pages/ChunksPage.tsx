/**
 * ChunksPage - 向量分块列表页
 *
 * v3 重构：按文档聚合展示，每个文档一张卡片
 * 卡片内可展开查看该文档下的所有分块详情
 */
import { useState, useEffect, useMemo } from 'react'
import {
  Database, Search, Download, FileText,
  Filter, BarChart3,
  Boxes, Clock, ChevronDown
} from 'lucide-react'
import api from '../services/api'

interface Chunk {
  id: string
  doc_id: string
  title: string
  category: string
  chunk_index: number
  content: string
  dimension: number
  metadata: any
}

interface DocGroup {
  title: string
  doc_id: string
  category: string
  chunks: Chunk[]
  created_at?: string
}

export default function ChunksPage() {
  const [allChunks, setAllChunks] = useState<Chunk[]>([])
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [categories, setCategories] = useState<{ name: string }[]>([])
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState<any>(null)
  const [expandedDocs, setExpandedDocs] = useState<Set<string>>(new Set())

  const loadAll = async () => {
    setLoading(true)
    try {
      // 拉取所有分块（不分页）用于前端聚合
      const r = await api.get('/chunks/list', {
        params: { page: 1, page_size: 5000, search, category },
      })
      setAllChunks(r.data.items || [])
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const loadStats = async () => {
    try {
      const r = await api.get('/chunks/stats')
      setStats(r.data)
    } catch (e) { /* ignore */ }
  }

  const loadCategories = async () => {
    try {
      const r = await api.get('/categories/')
      setCategories(r.data || [])
    } catch (e) { /* ignore */ }
  }

  useEffect(() => { loadAll(); loadStats(); loadCategories() }, [])
  useEffect(() => { loadAll() }, [category])

  const handleSearch = () => loadAll()

  const handleExport = () => {
    const url = `/api/chunks/export?${new URLSearchParams({ search, category }).toString()}`
    window.open(url, '_blank')
  }

  // 按文档聚合
  const docGroups = useMemo<DocGroup[]>(() => {
    const map = new Map<string, DocGroup>()
    for (const c of allChunks) {
      const key = c.doc_id || c.title
      if (!map.has(key)) {
        map.set(key, {
          title: c.title || '(未命名)',
          doc_id: c.doc_id,
          category: c.category || '默认',
          chunks: [],
        })
      }
      map.get(key)!.chunks.push(c)
    }
    // 按分块数量降序
    return Array.from(map.values()).sort((a, b) => b.chunks.length - a.chunks.length)
  }, [allChunks])

  const toggleExpand = (key: string) => {
    setExpandedDocs((prev) => {
      const n = new Set(prev)
      n.has(key) ? n.delete(key) : n.add(key)
      return n
    })
  }

  const expandAll = () => setExpandedDocs(new Set(docGroups.map((g) => g.doc_id)))
  const collapseAll = () => setExpandedDocs(new Set())

  return (
    <div className="space-y-6">
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Database className="h-6 w-6 text-blue-500" />
            向量分块列表
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            按文档聚合展示，共 {docGroups.length} 个文档 · {allChunks.length} 个分块
          </p>
        </div>
        <button
          onClick={handleExport}
          className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-green-500 to-emerald-600 text-white rounded-xl hover:shadow-lg"
        >
          <Download className="h-4 w-4" />
          导出 CSV
        </button>
      </div>

      {/* 统计卡片 */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <StatCard label="总分块数" value={stats.total_chunks} icon={<Database className="h-4 w-4" />} />
          <StatCard label="覆盖文档" value={stats.total_documents} icon={<FileText className="h-4 w-4" />} />
          <StatCard label="分类数" value={stats.total_categories} icon={<Filter className="h-4 w-4" />} />
          <StatCard label="TOP1 文档分块数" value={stats.by_document?.[0]?.[1] || 0} icon={<BarChart3 className="h-4 w-4" />} />
        </div>
      )}

      {/* 检索栏 */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex-1 min-w-[200px] relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="在分块内容中搜索..."
              className="w-full pl-10 pr-3 py-2 border border-gray-200 rounded-lg text-sm"
            />
          </div>
          <select
            value={category}
            onChange={(e) => { setCategory(e.target.value) }}
            className="px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white"
          >
            <option value="">全部分类</option>
            {categories.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
          <button onClick={handleSearch} className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm">
            搜索
          </button>
          <div className="border-l border-gray-200 pl-3 flex gap-1">
            <button onClick={expandAll} className="px-2 py-1 text-xs text-blue-600 hover:bg-blue-50 rounded">全部展开</button>
            <button onClick={collapseAll} className="px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 rounded">全部收起</button>
          </div>
        </div>
      </div>

      {/* 按文档聚合的卡片列表 */}
      {loading ? (
        <div className="p-12 text-center text-gray-400">加载中...</div>
      ) : docGroups.length === 0 ? (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-12 text-center text-gray-400">
          <Database className="h-12 w-12 mx-auto mb-3 text-gray-200" />
          <p>暂无分块数据</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {docGroups.map((group) => {
            const isExpanded = expandedDocs.has(group.doc_id)
            return (
              <div
                key={group.doc_id}
                className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden hover:border-blue-200 transition-colors"
              >
                {/* 卡片头部 */}
                <div
                  onClick={() => toggleExpand(group.doc_id)}
                  className="px-4 py-3 bg-gradient-to-r from-blue-50 to-indigo-50 border-b border-gray-100 cursor-pointer"
                >
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-white shadow-sm">
                      <Boxes className="h-5 w-5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-semibold text-gray-900 text-sm truncate">
                        {group.title}
                      </h3>
                      <div className="flex items-center gap-3 mt-0.5 text-[11px] text-gray-500">
                        <span className="flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {group.chunks.length} 个分块
                        </span>
                        <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-[10px]">
                          {group.category}
                        </span>
                      </div>
                    </div>
                    <ChevronDown
                      className={`h-5 w-5 text-gray-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                    />
                  </div>
                </div>

                {/* 展开的分块列表 */}
                {isExpanded && (
                  <div className="divide-y divide-gray-50 max-h-80 overflow-y-auto">
                    {group.chunks
                      .sort((a, b) => (a.chunk_index || 0) - (b.chunk_index || 0))
                      .map((chunk) => (
                        <div key={chunk.id} className="px-4 py-3 hover:bg-gray-50/50">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="px-1.5 py-0.5 bg-gray-100 rounded text-[10px] text-gray-600 font-mono">
                              #{chunk.chunk_index}
                            </span>
                            <span className="text-[10px] text-gray-400">{chunk.dimension}D</span>
                          </div>
                          <p className="text-xs text-gray-700 leading-relaxed line-clamp-4">
                            {chunk.content}
                          </p>
                        </div>
                      ))}
                  </div>
                )}

                {/* 收起状态提示 */}
                {!isExpanded && group.chunks.length > 0 && (
                  <div className="px-4 py-2 border-t border-gray-50">
                    <p className="text-xs text-gray-400 line-clamp-1">
                      {group.chunks[0].content?.substring(0, 80)}...
                    </p>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 p-3 flex items-center gap-3">
      <div className="w-10 h-10 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center">
        {icon}
      </div>
      <div>
        <div className="text-xs text-gray-500">{label}</div>
        <div className="text-xl font-bold text-gray-900">{value?.toLocaleString() || 0}</div>
      </div>
    </div>
  )
}
