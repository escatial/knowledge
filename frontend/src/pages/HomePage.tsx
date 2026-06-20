import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  FileText, Database, Search, TrendingUp, Layers, BookOpen, Library, MessageSquare,
  ChevronDown, ChevronUp, ArrowUpRight
} from 'lucide-react'
import { documentApi } from '../services/api'
import DragUpload from '../components/DragUpload'
import DocumentDetail from '../components/DocumentDetail'

interface Document {
  id: string
  title: string
  content: string
  category: string
  created_at: string
  updated_at: string
  file_type: string
}

interface StatsData {
  totalDocs: number
  totalChunks: number
  totalKnowledgeBases: number
  totalConversations: number
}

export default function HomePage() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [stats, setStats] = useState<StatsData>({
    totalDocs: 0,
    totalChunks: 0,
    totalKnowledgeBases: 0,
    totalConversations: 0
  })
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null)
  const [loading, setLoading] = useState(false)
  // 文档列表折叠状态：默认折叠（文档数>5 时），用户偏好持久化
  const [docListCollapsed, setDocListCollapsed] = useState<boolean>(() => {
    try {
      const raw = localStorage.getItem('home_doclist_collapsed_v1')
      return raw === 'true'
    } catch {
      return true
    }
  })
  useEffect(() => {
    try { localStorage.setItem('home_doclist_collapsed_v1', String(docListCollapsed)) } catch {}
  }, [docListCollapsed])

  useEffect(() => {
    loadDashboardData()
  }, [])

  const loadDashboardData = async () => {
    setLoading(true)
    try {
      const [docsRes, dashboardRes] = await Promise.all([
        documentApi.list(),
        documentApi.dashboardStats()
      ])

      setDocuments(docsRes.data || [])
      setStats({
        totalDocs: (docsRes.data || []).length,
        totalChunks: dashboardRes.data?.vector_store?.total_chunks || 0,
        totalKnowledgeBases: dashboardRes.data?.knowledge_base?.total || 0,
        totalConversations: dashboardRes.data?.qa_stats?.total_sessions || 0
      })
    } catch (error) {
      console.error('加载数据失败:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('确定要删除这个文档吗？')) return
    try {
      await documentApi.delete(id)
      loadDashboardData()
    } catch (error) {
      console.error('删除文档失败:', error)
    }
  }

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      loadDashboardData()
      return
    }
    setLoading(true)
    try {
      // 搜索功能可后续接入 searchApi
      const filtered = documents.filter(doc =>
        doc.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        doc.category.toLowerCase().includes(searchQuery.toLowerCase())
      )
      setDocuments(filtered)
    } catch (error) {
      console.error('搜索失败:', error)
    } finally {
      setLoading(false)
    }
  }

  const statCards = [
    {
      title: '文档总数',
      value: stats.totalDocs,
      icon: FileText,
      color: 'from-blue-500 to-blue-600',
      bgColor: 'bg-blue-50',
      textColor: 'text-blue-600',
      to: '/documents',
    },
    {
      title: '向量分块',
      value: stats.totalChunks,
      icon: Layers,
      color: 'from-purple-500 to-purple-600',
      bgColor: 'bg-purple-50',
      textColor: 'text-purple-600',
      to: '/chunks',
    },
    {
      title: '知识库数量',
      value: stats.totalKnowledgeBases,
      icon: Library,
      color: 'from-emerald-500 to-emerald-600',
      bgColor: 'bg-emerald-50',
      textColor: 'text-emerald-600',
      to: '/documents',
    },
    {
      title: '对话总数',
      value: stats.totalConversations,
      icon: MessageSquare,
      color: 'from-amber-500 to-amber-600',
      bgColor: 'bg-amber-50',
      textColor: 'text-amber-600',
      to: '/chat',
    },
  ]

  const navigate = useNavigate()

  return (
    <div className="space-y-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">工作台</h1>
          <p className="text-sm text-gray-500 mt-1">知识库数据概览与文档管理</p>
        </div>

      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((card) => {
          const Icon = card.icon
          return (
            <a
              key={card.title}
              href={card.to}
              onClick={(e) => { e.preventDefault(); navigate(card.to!) }}
              className="group bg-white rounded-2xl p-5 border border-gray-100 shadow-sm hover:shadow-md hover:border-blue-200 transition-all duration-200 cursor-pointer block"
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-500 font-medium">{card.title}</p>
                  <p className={`text-3xl font-bold mt-2 ${card.textColor}`}>
                    {loading ? (
                      <span className="inline-block w-8 h-8 border-2 border-gray-200 border-t-gray-400 rounded-full animate-spin" />
                    ) : (
                      card.value
                    )}
                  </p>
                </div>
                <div className={`w-12 h-12 rounded-xl ${card.bgColor} flex items-center justify-center`}>
                  <Icon className={`h-6 w-6 ${card.textColor}`} />
                </div>
              </div>
              <div className="mt-3 flex items-center justify-between text-xs">
                <span className="flex items-center gap-1 text-gray-400">
                  <TrendingUp className="h-3 w-3" />
                  <span>实时统计</span>
                </span>
                <span className={`flex items-center gap-0.5 ${card.textColor} opacity-0 group-hover:opacity-100 transition-opacity`}>
                  查看详情
                  <ArrowUpRight className="h-3 w-3" />
                </span>
              </div>
            </a>
          )
        })}
      </div>

      {/* 主内容区 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧：上传和搜索 */}
        <div className="lg:col-span-1 space-y-6">
          {/* 上传组件 */}
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
                <BookOpen className="h-4 w-4 text-blue-600" />
              </div>
              <h2 className="text-lg font-semibold text-gray-900">上传文档</h2>
            </div>
            <DragUpload onUploadSuccess={loadDashboardData} />
          </div>

          {/* 搜索 */}
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-8 h-8 rounded-lg bg-purple-50 flex items-center justify-center">
                <Search className="h-4 w-4 text-purple-600" />
              </div>
              <h2 className="text-lg font-semibold text-gray-900">文档搜索</h2>
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                placeholder="搜索文档标题或分类..."
                className="flex-1 px-4 py-2.5 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 text-sm"
              />
              <button
                onClick={handleSearch}
                className="px-4 py-2.5 bg-gray-900 text-white rounded-xl hover:bg-gray-800 transition-colors"
              >
                <Search className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        {/* 右侧：文档列表 */}
        <div className="lg:col-span-2">
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
            <div
              className="p-5 border-b border-gray-100 flex items-center justify-between cursor-pointer hover:bg-gray-50/50"
              onClick={() => setDocListCollapsed(!docListCollapsed)}
            >
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-emerald-50 flex items-center justify-center">
                  <Database className="h-4 w-4 text-emerald-600" />
                </div>
                <h2 className="text-lg font-semibold text-gray-900">文档列表</h2>
              </div>
              <span className="flex items-center gap-1 text-sm text-gray-400">
                <span>共 {documents.length} 个文档</span>
                <span className="ml-2 inline-flex items-center gap-0.5 px-2 py-0.5 rounded-md bg-gray-100 text-xs">
                  {docListCollapsed ? '展开' : '收起'}
                  {docListCollapsed ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
                </span>
              </span>
            </div>

            {/* 折叠内容区：grid-template-rows 平滑过渡，标题/触发按钮始终可见 */}
            <div
              className={`grid transition-[grid-template-rows] duration-300 ease-in-out ${
                docListCollapsed ? 'grid-rows-[0fr]' : 'grid-rows-[1fr]'
              }`}
            >
              <div className="overflow-hidden">
                {/* 任务 3.1：列表限高 + 独立滚动条（max-h-96 = 384px，超出滚动，不撑爆主界面） */}
                {/* 任务 3.3：自定义滚动条样式（细圆角，hover 变粗） */}
                <div className="max-h-96 overflow-y-auto dashboard-doc-scroll">

            {loading ? (
              <div className="p-12 text-center">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto" />
                <p className="mt-3 text-gray-400 text-sm">加载中...</p>
              </div>
            ) : documents.length === 0 ? (
              <div className="p-12 text-center text-gray-400">
                <FileText className="h-12 w-12 mx-auto mb-4 text-gray-200" />
                <p className="text-sm">暂无文档，请上传文件</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-50">
                {documents.map((doc) => {
                  // 任务 3.2：根据分类名分配稳定色（hash 颜色），分类标签视觉强化
                  const catHash = (doc.category || '默认').split('').reduce((a, c) => a + c.charCodeAt(0), 0)
                  const palette = [
                    { bg: 'bg-blue-50', text: 'text-blue-700', ring: 'ring-blue-200' },
                    { bg: 'bg-emerald-50', text: 'text-emerald-700', ring: 'ring-emerald-200' },
                    { bg: 'bg-purple-50', text: 'text-purple-700', ring: 'ring-purple-200' },
                    { bg: 'bg-amber-50', text: 'text-amber-700', ring: 'ring-amber-200' },
                    { bg: 'bg-rose-50', text: 'text-rose-700', ring: 'ring-rose-200' },
                    { bg: 'bg-cyan-50', text: 'text-cyan-700', ring: 'ring-cyan-200' },
                    { bg: 'bg-indigo-50', text: 'text-indigo-700', ring: 'ring-indigo-200' },
                  ]
                  const cat = palette[catHash % palette.length]
                  return (
                  <div
                    key={doc.id}
                    className="p-4 hover:bg-gray-50/80 transition-colors cursor-pointer group"
                    onClick={() => setSelectedDoc(doc)}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-3 min-w-0 flex-1">
                        <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
                          <FileText className="h-4 w-4 text-blue-500" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <h3 className="font-semibold text-gray-900 text-sm truncate">
                            {doc.title}
                          </h3>
                          <div className="flex items-center gap-1.5 mt-1 text-xs">
                            {/* 任务 3.2：分类标签 — 强色块 + 加粗 + 边框 + ring */}
                            <span className={`inline-flex items-center px-2 py-0.5 rounded-md font-semibold text-[11px] ${cat.bg} ${cat.text} ring-1 ${cat.ring}`}>
                              {doc.category}
                            </span>
                            <span className="text-gray-300">·</span>
                            <span className="text-gray-400">{new Date(doc.created_at).toLocaleDateString()}</span>
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            setSelectedDoc(doc)
                          }}
                          className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
                        >
                          <Search className="h-3.5 w-3.5 text-gray-400" />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDelete(doc.id)
                          }}
                          className="p-2 hover:bg-red-50 rounded-lg transition-colors"
                        >
                          <FileText className="h-3.5 w-3.5 text-red-400" />
                        </button>
                      </div>
                    </div>
                  </div>
                  )
                })}
              </div>
            )}
                </div>{/* /dashboard-doc-scroll */}
              </div>{/* /overflow-hidden */}
            </div>{/* /grid transition wrapper */}
          </div>
        </div>
      </div>

      {/* 文档详情弹窗 */}
      {selectedDoc && (
        <DocumentDetail
          document={selectedDoc}
          onClose={() => setSelectedDoc(null)}
        />
      )}

    </div>
  )
}
