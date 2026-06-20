import { useState, useEffect } from 'react'
import { Outlet, useLocation, Link } from 'react-router-dom'
import {
  Database, Network, MessageSquare,
  Settings, Menu, LayoutDashboard, Sparkles,
  Search, ChevronRight, Boxes
} from 'lucide-react'
import KBSelector from './KBSelector'

const navItems = [
  { path: '/', icon: LayoutDashboard, label: '工作台', description: '数据概览' },
  { path: '/documents', icon: Database, label: '文档管理', description: '上传与列表' },
  { path: '/graph', icon: Network, label: '知识图谱', description: '2D/3D 可视化' },
  { path: '/search', icon: Search, label: '混合检索', description: '语义+图谱' },
  { path: '/chat', icon: MessageSquare, label: '智能问答', description: 'AI 助手' },
  { path: '/chunks', icon: Boxes, label: '向量分块', description: '运维与排查' },
  { path: '/settings', icon: Settings, label: '系统设置', description: '配置管理' },
]

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()
  // 任务 2：KB 切换器默认隐藏，可在「系统设置 → 高级」中开启
  const [kbSelectorVisible, setKbSelectorVisible] = useState<boolean>(() => {
    try {
      return localStorage.getItem('kb_selector_visible') === 'true'
    } catch {
      return false
    }
  })

  // 监听设置变更（从设置页 broadcast）
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      setKbSelectorVisible(!!detail?.visible)
    }
    window.addEventListener('kb-selector-toggle', handler)
    return () => window.removeEventListener('kb-selector-toggle', handler)
  }, [])

  const currentNav = navItems.find(item => item.path === location.pathname)

  return (
    <div className="h-screen overflow-hidden bg-gray-50/80 flex">
      {/* 移动端遮罩 */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/40 backdrop-blur-sm z-40 lg:hidden transition-opacity"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* 侧边栏 - OS 风格 */}
      <aside
        className={`
          fixed lg:static inset-y-0 left-0 z-50
          w-72 bg-white border-r border-gray-100
          transform transition-transform duration-300 ease-out
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
          flex flex-col shadow-xl lg:shadow-none
          h-screen lg:h-screen
        `}
      >
        {/* Logo 区域 - 渐变风格 */}
        <div className="flex-shrink-0 p-6 border-b border-gray-50">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-blue-500 via-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-200">
              <Sparkles className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-gray-900 tracking-tight">知识库</h1>
              <p className="text-[11px] text-gray-400 font-medium tracking-wide">KNOWLEDGE OS</p>
            </div>
          </div>
        </div>

        {/* 任务 2：知识库选择器（默认隐藏，需要时在「系统设置 → 高级」中开启） */}
        {kbSelectorVisible && (
          <div className="flex-shrink-0 p-4 border-b border-gray-50">
            <KBSelector />
          </div>
        )}

        {/* 导航菜单 - 侧边栏内容独立滚动 */}
        <nav className="flex-1 min-h-0 p-4 space-y-1 overflow-y-auto app-aside-scroll">
          <div className="px-3 pb-2 pt-1">
            <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
              主菜单
            </p>
          </div>
          
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive = location.pathname === item.path
            return (
              <Link
                key={item.path}
                to={item.path}
                onClick={() => setSidebarOpen(false)}
                className={`
                  flex items-center gap-3 px-4 py-3 rounded-xl text-sm
                  transition-all duration-200 group relative
                  ${isActive
                    ? 'bg-gradient-to-r from-blue-50 to-indigo-50 text-blue-700 shadow-sm border border-blue-100/50'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                  }
                `}
              >
                <div className={`
                  w-9 h-9 rounded-lg flex items-center justify-center transition-colors
                  ${isActive ? 'bg-blue-100 text-blue-600' : 'bg-gray-100 text-gray-500 group-hover:bg-gray-200'}
                `}>
                  <Icon className="h-[18px] w-[18px]" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className={`font-semibold ${isActive ? 'text-blue-700' : ''}`}>
                    {item.label}
                  </p>
                  <p className="text-[11px] text-gray-400 truncate">
                    {item.description}
                  </p>
                </div>
                {isActive && (
                  <ChevronRight className="h-4 w-4 text-blue-400" />
                )}
              </Link>
            )
          })}
        </nav>

        {/* 底部信息 - 系统状态卡片 */}
        <div className="flex-shrink-0 p-4 border-t border-gray-50">
          <div className="bg-gradient-to-br from-gray-50 to-gray-100/50 rounded-xl p-4 border border-gray-100">
            <div className="flex items-center justify-between mb-2">
              <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider">系统状态</p>
              <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse shadow-sm shadow-green-200" />
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-500">向量服务</span>
                <span className="text-green-600 font-medium">正常</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-500">AI 模型</span>
                <span className="text-green-600 font-medium">就绪</span>
              </div>
            </div>
          </div>
          <p className="text-center text-[11px] text-gray-300 mt-3">v1.0.0 · Knowledge OS</p>
        </div>
      </aside>

      {/* 主内容区 */}
      <div className="flex-1 flex flex-col min-w-0 h-screen overflow-hidden">
        {/* 顶部栏 - 玻璃拟态风格 */}
        <header className="flex-shrink-0 z-30 bg-white/80 backdrop-blur-xl border-b border-gray-100 px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setSidebarOpen(true)}
              className="lg:hidden p-2.5 hover:bg-gray-100 rounded-xl transition-colors"
            >
              <Menu className="h-5 w-5 text-gray-600" />
            </button>

            <div className="hidden lg:flex items-center gap-2 text-sm text-gray-400">
              <span>Knowledge OS</span>
              <ChevronRight className="h-3 w-3" />
              <span className="text-gray-700 font-medium">
                {currentNav?.label || '工作台'}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-gray-50 rounded-lg border border-gray-100">
              <div className="w-1.5 h-1.5 bg-green-500 rounded-full" />
              <span className="text-xs text-gray-500 font-medium">运行正常</span>
            </div>
          </div>
        </header>

        {/* 页面内容
            任务：固定主区高度 = 视口 - 顶部栏；独立滚动条，仅 main 内部滚动
            不再触发整个页面（body / html）滚动 */}
        <main className="flex-1 min-h-0 p-6 lg:p-8 overflow-y-auto app-main-scroll">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
