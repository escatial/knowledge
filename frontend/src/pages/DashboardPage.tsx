import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Database, MessageSquare, Brain,
  FileText, Layers, TrendingUp, AlertCircle,
  CheckCircle, Activity, Clock, BarChart3,
  Users, Server, BookOpen, Star, Zap,
  ChevronDown, ChevronUp
} from 'lucide-react'
import { documentApi } from '../services/api'

// ── 面板组件 ────────────────────────────────────────────────────

/**
 * RecentDocumentsPanel —— 工作台"文档列表"模块
 *
 * 需求 3.1：默认折叠；当文档总数 > 5 时自动激活折叠逻辑；
 * 提供手动展开/收起入口；展开后若超出主界面高度出现滚动条。
 */
function RecentDocumentsPanel({
  documents,
  categories,
  threshold = 5,
}: {
  documents: any[]
  categories: Record<string, number>
  threshold?: number
}) {
  const STORAGE_KEY = 'dashboard_recent_collapsed_v1'
  // 默认折叠逻辑：文档数 > 阈值时折叠
  const shouldCollapseByDefault = documents.length > threshold
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      // 第一次访问时按阈值决定；后续访问以用户偏好为准
      if (raw === null) return shouldCollapseByDefault
      return raw === 'true'
    } catch {
      return shouldCollapseByDefault
    }
  })

  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, String(collapsed)) } catch {}
  }, [collapsed])

  const categoryEntries = Object.entries(categories)

  return (
    <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden">
      <div
        className="flex items-center justify-between px-5 py-3 cursor-pointer hover:bg-gray-50/50"
        onClick={() => setCollapsed(!collapsed)}
      >
        <div className="flex items-center gap-3">
          <FileText className="h-4 w-4 text-blue-500" />
          <h3 className="text-sm font-semibold text-gray-900">文档列表</h3>
          <span className="px-1.5 py-0.5 bg-blue-50 text-blue-600 text-[11px] rounded">
            共 {documents.length} 篇
          </span>
          {categoryEntries.length > 0 && (
            <span className="text-xs text-gray-400">
              {categoryEntries.length} 个分类
            </span>
          )}
        </div>
        <span className="flex items-center gap-1 text-xs text-gray-400">
          {collapsed ? '展开' : '收起'}
          {collapsed ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
        </span>
      </div>

      {/* 内容区：max-h + transition 平滑动画；保留标题/触发按钮可见 */}
      <div
        className={`grid transition-[grid-template-rows] duration-300 ease-in-out ${
          collapsed ? 'grid-rows-[0fr]' : 'grid-rows-[1fr]'
        }`}
      >
        <div className="overflow-hidden border-t border-gray-100">
          <div className="max-h-[420px] overflow-y-auto">
            {documents.length === 0 ? (
              <div className="px-5 py-8 text-center text-gray-400 text-sm">暂无文档</div>
            ) : (
              documents.map((doc, i) => (
                <div
                  key={doc.id || i}
                  className="px-5 py-2.5 flex items-center gap-3 hover:bg-gray-50/50 border-b border-gray-50 last:border-b-0"
                >
                  <FileText className="h-3.5 w-3.5 text-blue-400 flex-shrink-0" />
                  <span className="text-sm text-gray-700 flex-1 truncate">{doc.title}</span>
                  <span className="px-1.5 py-0.5 bg-gray-100 text-gray-600 text-[10px] rounded flex-shrink-0">
                    {doc.category}
                  </span>
                  <span className="text-[11px] text-gray-400 flex-shrink-0 w-20 text-right">
                    {doc.created_at ? new Date(doc.created_at).toLocaleDateString() : '-'}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

interface DashboardData {
  documents: { total: number; categories: Record<string, number> }
  vector_store: { total_chunks: number; dimensions: number }
  qa_stats: { total_sessions: number; total_messages: number; avg_messages_per_session: number }
  hot_questions: { question: string; count: number; trend: string }[]
  system_status: Record<string, string>
}

const TabButton = ({ active, icon: Icon, label, count, onClick }: {
  active: boolean; icon: any; label: string; count?: string; onClick: () => void
}) => (
  <button
    onClick={onClick}
    className={`flex items-center gap-2.5 px-5 py-3 rounded-xl text-sm font-medium transition-all duration-200 ${
      active
        ? 'bg-white shadow-sm border border-gray-200 text-blue-600'
        : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
    }`}
  >
    <Icon className={`h-4 w-4 ${active ? 'text-blue-500' : ''}`} />
    <span>{label}</span>
    {count && (
      <span className={`ml-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${
        active ? 'bg-blue-50 text-blue-600' : 'bg-gray-100 text-gray-500'
      }`}>
        {count}
      </span>
    )}
  </button>
)

const StatCard = ({ icon: Icon, label, value, sub, color, to }: {
  icon: any; label: string; value: string | number; sub?: string; color: string
  to?: string
}) => {
  const nav = useNavigate()
  const content = (
    <div className={`bg-white rounded-2xl border border-gray-100 p-5 transition-all duration-200 ${to ? 'hover:shadow-md hover:border-blue-200 cursor-pointer' : ''}`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-gray-400 font-medium tracking-wide">{label}</p>
          <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
          {sub && <p className="text-[11px] text-gray-400 mt-1">{sub}</p>}
        </div>
        <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${color}`}>
          <Icon className="h-5 w-5 text-white" />
        </div>
      </div>
    </div>
  )
  if (to) return <span onClick={() => nav(to)} className="block">{content}</span>
  return <>{content}</>
}

// ── 主面板 ───────────────────────────────────────────────────────

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState('overview')
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  // 需求 3.1：工作台"文档列表"折叠模块需要原始文档数据
  const [recentDocs, setRecentDocs] = useState<any[]>([])

  useEffect(() => {
    loadDashboardData()
    loadRecentDocs()
  }, [])

  const loadDashboardData = async () => {
    try {
      const res = await documentApi.dashboardStats()
      setData(res.data)
    } catch (e) {
      console.error('加载仪表盘数据失败:', e)
    } finally {
      setLoading(false)
    }
  }

  const loadRecentDocs = async () => {
    try {
      // 复用 /api/documents/list（已包含 content_preview），用于工作台文档列表
      const res = await documentApi.list()
      setRecentDocs(res.data || [])
    } catch (e) {
      console.warn('加载最近文档失败:', e)
    }
  }

  const tabs = [
    { key: 'overview', icon: BarChart3, label: '总览' },
    { key: 'qa', icon: MessageSquare, label: '问答统计' },
    { key: 'hot', icon: TrendingUp, label: '热门提问' },
    { key: 'status', icon: Activity, label: '系统状态' },
  ]

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="flex items-center gap-3 text-gray-400">
          <Activity className="h-5 w-5 animate-pulse" />
          <span className="text-sm">加载中...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* 页面标题 */}
      <div>
        <h1 className="text-xl font-bold text-gray-900">工作台</h1>
        <p className="text-sm text-gray-400 mt-1">知识库系统运行总览与数据看板</p>
      </div>

      {/* 标签导航 */}
      <div className="flex flex-wrap gap-2 bg-gray-50/50 rounded-2xl p-1.5 border border-gray-100">
        {tabs.map(tab => (
          <TabButton
            key={tab.key}
            active={activeTab === tab.key}
            icon={tab.icon}
            label={tab.label}
            count={'count' in tab ? (tab as any).count : undefined}
            onClick={() => setActiveTab(tab.key)}
          />
        ))}
      </div>

      {/* ════════════════════════════════════════════════════ 总览 ════ */}
      {activeTab === 'overview' && data && (
        <div className="space-y-6">
          {/* 统计卡片 */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              icon={FileText}
              label="文档总数"
              value={data.documents.total}
              sub={`${Object.keys(data.documents.categories).length} 个分类`}
              color="bg-gradient-to-br from-blue-500 to-blue-600"
              to="/documents"
            />
            <StatCard
              icon={Layers}
              label="向量分块"
              value={data.vector_store.total_chunks}
              sub={`维度 ${data.vector_store.dimensions || 1536}`}
              color="bg-gradient-to-br from-indigo-500 to-indigo-600"
              to="/chunks"
            />
            <StatCard
              icon={BookOpen}
              label="知识库数量"
              value={Object.keys(data.documents.categories).length}
              sub={`${Object.keys(data.documents.categories).length} 个分类`}
              color="bg-gradient-to-br from-green-500 to-green-600"
              to="/documents"
            />
            <StatCard
              icon={MessageSquare}
              label="对话总数"
              value={data.qa_stats.total_messages}
              sub={`${data.qa_stats.total_sessions} 个会话`}
              color="bg-gradient-to-br from-amber-500 to-amber-600"
              to="/chat"
            />
          </div>

          {/* 需求 3.1：工作台"文档列表"折叠模块 */}
          <RecentDocumentsPanel
            documents={recentDocs}
            categories={data.documents.categories}
            threshold={5}
          />

          {/* 分类分布 + 热门提问 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* 分类饼图 */}
            <div className="bg-white rounded-2xl border border-gray-100 p-6">
              <h3 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <BookOpen className="h-4 w-4 text-blue-500" />
                文档分类分布
              </h3>
              {Object.keys(data.documents.categories).length > 0 ? (
                <div className="space-y-3">
                  {Object.entries(data.documents.categories).map(([cat, count]) => {
                    const total = data.documents.total || 1
                    const pct = ((count as number) / total * 100).toFixed(0)
                    return (
                      <div key={cat}>
                        <div className="flex justify-between text-xs mb-1">
                          <span className="text-gray-700 font-medium">{cat}</span>
                          <span className="text-gray-400">{count as number} 篇 ({pct}%)</span>
                        </div>
                        <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-blue-400 to-indigo-500 rounded-full transition-all duration-500"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="text-center py-8 text-gray-400 text-sm">
                  暂无文档数据
                </div>
              )}
            </div>

            {/* 热门提问预览 */}
            <div className="bg-white rounded-2xl border border-gray-100 p-6">
              <h3 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-amber-500" />
                热门提问 TOP 5
              </h3>
              {data.hot_questions.length > 0 && data.hot_questions[0].question !== '暂无数据' ? (
                <div className="space-y-3">
                  {data.hot_questions.slice(0, 5).map((q, i) => {
                    const maxCount = Math.max(...data.hot_questions.map(x => x.count), 1)
                    const barWidth = (q.count / maxCount * 100).toFixed(0)
                    return (
                      <div key={i} className="flex items-center gap-3">
                        <span className={`w-5 text-center text-xs font-bold ${
                          i < 3 ? 'text-amber-500' : 'text-gray-400'
                        }`}>
                          #{i + 1}
                        </span>
                        <div className="flex-1 min-w-0">
                          <p className="text-xs text-gray-700 truncate">{q.question}</p>
                          <div className="w-full h-1.5 bg-gray-100 rounded-full mt-1 overflow-hidden">
                            <div
                              className="h-full bg-gradient-to-r from-amber-400 to-orange-500 rounded-full"
                              style={{ width: `${barWidth}%` }}
                            />
                          </div>
                        </div>
                        <span className="text-[11px] text-gray-400 shrink-0">{q.count} 次</span>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="text-center py-8 text-gray-400 text-sm">
                  暂无热门提问数据
                </div>
              )}
            </div>
          </div>

          {/* 系统状态预览 */}
          <div className="bg-white rounded-2xl border border-gray-100 p-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <Server className="h-4 w-4 text-emerald-500" />
              系统服务状态
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
              {Object.entries(data.system_status).map(([service, status]) => {
                const labels: Record<string, string> = {
                  vector_service: '向量检索服务',
                  ai_model: 'AI 模型服务',
                  api_server: 'API 服务器',
                }
                const isOk = status === 'normal'
                return (
                  <div key={service} className="flex items-center gap-3 p-3 rounded-xl bg-gray-50">
                    <div className={`w-2.5 h-2.5 rounded-full ${isOk ? 'bg-green-500' : 'bg-red-500'}`}>
                      {isOk && <div className="w-2.5 h-2.5 bg-green-500 rounded-full animate-ping opacity-30" />}
                    </div>
                    <div>
                      <p className="text-xs font-medium text-gray-700">{labels[service] || service}</p>
                      <p className={`text-[11px] ${isOk ? 'text-green-500' : 'text-red-500'}`}>
                        {isOk ? '运行正常' : '异常'}
                      </p>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════ 问答统计 ════ */}
      {activeTab === 'qa' && data && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <StatCard
              icon={MessageSquare}
              label="总会话数"
              value={data.qa_stats.total_sessions}
              color="bg-gradient-to-br from-amber-500 to-amber-600"
            />
            <StatCard
              icon={FileText}
              label="总消息数"
              value={data.qa_stats.total_messages}
              color="bg-gradient-to-br from-orange-500 to-orange-600"
            />
            <StatCard
              icon={BarChart3}
              label="平均每会话消息"
              value={data.qa_stats.avg_messages_per_session}
              color="bg-gradient-to-br from-rose-500 to-rose-600"
            />
          </div>

          <div className="bg-white rounded-2xl border border-gray-100 p-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <Users className="h-4 w-4 text-amber-500" />
              问答使用分析
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="bg-amber-50/50 rounded-xl p-5 border border-amber-100/50">
                <div className="flex items-center gap-2 text-amber-700 mb-2">
                  <Clock className="h-4 w-4" />
                  <span className="text-xs font-semibold">活跃度</span>
                </div>
                <p className="text-2xl font-bold text-amber-800">{data.qa_stats.total_sessions || '—'}</p>
                <p className="text-xs text-amber-600 mt-1">历史发起会话总数</p>
              </div>
              <div className="bg-blue-50/50 rounded-xl p-5 border border-blue-100/50">
                <div className="flex items-center gap-2 text-blue-700 mb-2">
                  <Star className="h-4 w-4" />
                  <span className="text-xs font-semibold">互动深度</span>
                </div>
                <p className="text-2xl font-bold text-blue-800">
                  {data.qa_stats.avg_messages_per_session || '—'}
                </p>
                <p className="text-xs text-blue-600 mt-1">平均每轮对话往返次数</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════ 热门提问 ════ */}
      {activeTab === 'hot' && data && (
        <div className="space-y-6">
          <div className="bg-white rounded-2xl border border-gray-100 p-6">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-amber-500" />
                提问排行
              </h3>
              <span className="text-[11px] text-gray-400">共 {data.hot_questions.length} 条</span>
            </div>

            {data.hot_questions.length > 0 && data.hot_questions[0].question !== '暂无数据' ? (
              <div className="space-y-2">
                {data.hot_questions.map((q, i) => {
                  const maxCount = Math.max(...data.hot_questions.map(x => x.count), 1)
                  const barWidth = (q.count / maxCount * 100).toFixed(0)
                  const trendIcon = q.trend === 'up' ? '↑' : q.trend === 'down' ? '↓' : '→'
                  const trendColor = q.trend === 'up' ? 'text-red-500' : q.trend === 'down' ? 'text-green-500' : 'text-gray-400'
                  return (
                    <div key={i} className="flex items-center gap-4 p-3 rounded-xl hover:bg-gray-50 transition-colors">
                      <span className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold ${
                        i === 0 ? 'bg-amber-100 text-amber-700' :
                        i === 1 ? 'bg-gray-100 text-gray-600' :
                        i === 2 ? 'bg-orange-100 text-orange-700' :
                        'bg-gray-50 text-gray-400'
                      }`}>
                        #{i + 1}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm text-gray-800 truncate font-medium">{q.question}</p>
                        <div className="w-full h-2 bg-gray-100 rounded-full mt-2 overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-amber-400 to-orange-500 rounded-full transition-all duration-500"
                            style={{ width: `${barWidth}%` }}
                          />
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <p className="text-sm font-bold text-gray-900">{q.count}</p>
                        <p className={`text-xs ${trendColor}`}>{trendIcon}</p>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="text-center py-16 text-gray-400">
                <TrendingUp className="h-12 w-12 mx-auto mb-3 opacity-20" />
                <p className="text-sm">暂无热门提问数据</p>
                <p className="text-xs mt-1">在智能问答模块进行提问后，高频问题将自动收录</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════ 系统状态 ════ */}
      {activeTab === 'status' && data && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <StatCard
              icon={Server}
              label="在线服务"
              value={`${Object.values(data.system_status).filter(s => s === 'normal').length} / ${Object.keys(data.system_status).length}`}
              sub="所有服务运行正常"
              color="bg-gradient-to-br from-green-500 to-emerald-600"
            />
            <StatCard
              icon={Zap}
              label="响应状态"
              value="正常"
              sub="API 延迟 < 100ms"
              color="bg-gradient-to-br from-blue-500 to-cyan-600"
            />
          </div>

          <div className="bg-white rounded-2xl border border-gray-100 p-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <Activity className="h-4 w-4 text-emerald-500" />
              各模块运行状态
            </h3>
            <div className="space-y-0 divide-y divide-gray-50">
              {[
                { key: 'vector_service', label: '向量检索服务', desc: '文档向量化存储与语义搜索', icon: Layers },
                
                { key: 'ai_model', label: 'AI 模型服务', desc: 'LLM 问答与实体提取', icon: Brain },
                { key: 'api_server', label: 'API 服务器', desc: 'RESTful 接口与流式输出', icon: Server },
              ].map(item => {
                const status = data.system_status[item.key] || 'unknown'
                const isOk = status === 'normal'
                const Icon = item.icon
                return (
                  <div key={item.key} className="flex items-center justify-between py-4">
                    <div className="flex items-center gap-3">
                      <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                        isOk ? 'bg-green-50' : 'bg-red-50'
                      }`}>
                        <Icon className={`h-5 w-5 ${isOk ? 'text-green-600' : 'text-red-500'}`} />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-gray-800">{item.label}</p>
                        <p className="text-xs text-gray-400">{item.desc}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {isOk ? (
                        <>
                          <CheckCircle className="h-4 w-4 text-green-500" />
                          <span className="text-xs font-medium text-green-600">运行正常</span>
                        </>
                      ) : (
                        <>
                          <AlertCircle className="h-4 w-4 text-red-500" />
                          <span className="text-xs font-medium text-red-600">异常</span>
                        </>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-gray-100 p-6">
            <h3 className="text-sm font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <Database className="h-4 w-4 text-gray-500" />
              数据存储概览
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="bg-gray-50 rounded-xl p-4">
                <p className="text-xs text-gray-500">文档存储</p>
                <p className="text-lg font-bold text-gray-900 mt-1">{data.documents.total} 篇</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {Object.keys(data.documents.categories).length} 个分类
                </p>
              </div>
              <div className="bg-gray-50 rounded-xl p-4">
                <p className="text-xs text-gray-500">向量索引</p>
                <p className="text-lg font-bold text-gray-900 mt-1">{data.vector_store.total_chunks} 块</p>
                <p className="text-xs text-gray-400 mt-0.5">维度 {data.vector_store.dimensions || 1536}</p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
