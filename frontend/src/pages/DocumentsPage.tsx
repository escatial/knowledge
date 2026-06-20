import { useState, useEffect, useMemo } from 'react'
import {
  FileText, Upload, Trash2, Eye,
  ChevronDown, Search, X, Loader2,
  Plus, FolderTree, Edit3, FolderPlus,
  LayoutGrid, List as ListIcon, RotateCcw,
  Download, ArrowLeft, FolderInput, History
} from 'lucide-react'
import { documentApi, categoryApi, knowledgeBaseApi } from '../services/api'
import { useKB } from '../contexts/KBContext'
import DragUpload from '../components/DragUpload'
import DocumentDetail from '../components/DocumentDetail'
import RecycleBinPage from './RecycleBinPage'
// 任务 P0-4：版本对比 Modal
import DocumentVersionModal from '../components/DocumentVersionModal'
// 任务 P1-2 / T2：标签选择器
import TagPicker from '../components/TagPicker'
import type { Document } from '../types'

interface Category {
  id?: string
  name: string
  strategy: string
  chunk_size?: number
  overlap?: number
}

const STRATEGY_OPTIONS = [
  { value: 'auto', label: '智能推荐' },
  { value: 'recursive', label: '递归分块' },
  { value: 'fixed', label: '固定大小' },
  { value: 'structure', label: '基于结构' },
  { value: 'semantic', label: '语义分块' },
  { value: 'naive', label: '简单分块' },
  { value: 'general', label: '通用分块' },
  { value: 'intelligent', label: '智能分块' },
]

export default function DocumentsPage() {
  const { currentKBId, knowledgeBases } = useKB()
  const [documents, setDocuments] = useState<Document[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [selectedCategory, setSelectedCategory] = useState<string>('')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const [showUpload, setShowUpload] = useState(false)
  const [showRecycle, setShowRecycle] = useState(false)
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null)
  // 任务 P0-4：版本对比 Modal
  const [versionDocId, setVersionDocId] = useState<string | null>(null)
  // 任务 P1-2：标签筛选
  const [selectedTags, setSelectedTags] = useState<string[]>([])

  // 视图模式：list=列表 / grouped=按分类分组
  const [viewMode, setViewMode] = useState<'list' | 'grouped'>('grouped')

  // 分类下钻查看（需求3：进入分类）
  const [drillCategory, setDrillCategory] = useState<string | null>(null)

  // 分类管理状态
  const [editingCategory, setEditingCategory] = useState<Category | null>(null)
  const [newCategory, setNewCategory] = useState<Category | null>(null)

  // 任务 4：文档迁移状态（{ ids, target } 为 null 时弹窗隐藏）
  const [migrateDialog, setMigrateDialog] = useState<{ ids: string[]; target: string } | null>(null)
  const [opLogOpen, setOpLogOpen] = useState(false)

  // 任务 2.2：SSE 进度状态（null=待确认；set=迁移中/已结束）
  const [migrateProgress, setMigrateProgress] = useState<{
    running: boolean
    total: number
    done: number
    failed: number
    current: string | null
    failedIds: string[]
    perFile: Record<string, { ok: boolean; title?: string; chunks?: number; error?: string }>
    summary: any | null
  } | null>(null)

  useEffect(() => {
    loadData()
  }, [selectedCategory, currentKBId])

  // 监听全局 kb-changed 事件
  useEffect(() => {
    const handler = () => loadData()
    window.addEventListener('kb-changed', handler)
    return () => window.removeEventListener('kb-changed', handler)
  }, [selectedCategory, currentKBId])

  const loadData = async () => {
    setLoading(true)
    try {
      const [docsRes, catsRes] = await Promise.all([
        documentApi.list(selectedCategory || undefined, currentKBId),
        categoryApi.getAll()
      ])
      setDocuments(docsRes.data || [])
      setCategories(catsRes.data || [])
    } catch (error) {
      console.error('加载数据失败:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (id: string) => {
    const doc = documents.find((d) => d.id === id)
    if (!doc) return
    if (!confirm(
      `确定要删除「${doc.title}」吗？\n\n` +
      `此操作将：\n` +
      `• 删除文档的所有向量数据\n` +
      `• 级联删除知识图谱中相关节点与关系\n` +
      `• 文档将进入回收站，7 天内可恢复`
    )) return
    try {
      const r = await documentApi.delete(id)
      const cascade = (r.data as any).cascade
      if (cascade) {
        console.log(`级联清理图谱: ${cascade.removed_nodes} 节点, ${cascade.removed_edges} 边`)
      }
      loadData()
    } catch (error) {
      console.error('删除失败:', error)
    }
  }

  const handleBatchDelete = async () => {
    if (!confirm(
      `确定要删除选中的 ${selectedDocs.size} 个文档吗？\n\n` +
      `此操作将：\n` +
      `• 删除所有选中文档的向量数据\n` +
      `• 级联删除知识图谱中相关节点与关系\n` +
      `• 文档将进入回收站，7 天内可恢复`
    )) return
    try {
      let totalNodes = 0, totalEdges = 0
      for (const id of selectedDocs) {
        const r = await documentApi.delete(id)
        const c = (r.data as any).cascade
        if (c) {
          totalNodes += c.removed_nodes || 0
          totalEdges += c.removed_edges || 0
        }
      }
      console.log(`批量删除完成: 图谱清理 ${totalNodes} 节点, ${totalEdges} 边`)
      setSelectedDocs(new Set())
      loadData()
    } catch (error) {
      console.error('批量删除失败:', error)
    }
  }

  const toggleSelect = (id: string) => {
    const newSet = new Set(selectedDocs)
    if (newSet.has(id)) {
      newSet.delete(id)
    } else {
      newSet.add(id)
    }
    setSelectedDocs(newSet)
  }

  const toggleSelectAll = () => {
    if (selectedDocs.size === filteredDocs.length) {
      setSelectedDocs(new Set())
    } else {
      setSelectedDocs(new Set(filteredDocs.map(d => d.id)))
    }
  }

  const handleSaveCategory = async (cat: Category, isNew: boolean) => {
    try {
      if (isNew) {
        await categoryApi.create(cat.name, cat.strategy, cat.chunk_size, cat.overlap)
        setNewCategory(null)
      } else {
        await categoryApi.update(cat.name, cat.strategy, cat.chunk_size, cat.overlap)
        setEditingCategory(null)
      }
      loadData()
    } catch (error: any) {
      alert(error.response?.data?.error || '操作失败')
    }
  }

  const handleDeleteCategory = async (name: string) => {
    if (!confirm(`确定要删除分类"${name}"吗？相关文档不会被删除，但会失去分类关联。`)) return
    try {
      await categoryApi.delete(name)
      if (selectedCategory === name) setSelectedCategory('')
      loadData()
    } catch (error: any) {
      alert(error.response?.data?.error || '删除失败')
    }
  }

  const filteredDocs = documents.filter(doc =>
    !searchQuery ||
    doc.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    doc.category.toLowerCase().includes(searchQuery.toLowerCase())
  )

  // 按分类分组（grouped 视图用）
  const groupedDocs = useMemo(() => {
    const map = new Map<string, Document[]>()
    for (const d of filteredDocs) {
      const cat = d.category || '默认'
      if (!map.has(cat)) map.set(cat, [])
      map.get(cat)!.push(d)
    }
    return map
  }, [filteredDocs])

  // 修改文档的分类（拖入新分类）
  const handleChangeDocCategory = async (docId: string, newCat: string) => {
    try {
      await documentApi.updateCategory(docId, newCat)
      loadData()
    } catch (e) {
      console.error('更新文档分类失败:', e)
    }
  }

  // 任务 4：打开迁移确认弹窗（单/批）
  const openMigrateDialog = (ids: string[]) => {
    if (ids.length === 0) return
    setMigrateDialog({ ids, target: '' })
  }

  // 任务 4 + 2.2：执行迁移（SSE 流式进度 + 失败重试）
  const handleConfirmMigrate = async () => {
    if (!migrateDialog || !migrateDialog.target) return
    const ids = migrateDialog.ids
    const target = migrateDialog.target
    // 关闭确认弹窗，开启进度态
    setMigrateDialog(null)
    setMigrateProgress({
      running: true, total: ids.length, done: 0, failed: 0,
      current: null, failedIds: [], perFile: {}, summary: null,
    })
    try {
      const res = await documentApi.migrateBatchStream(ids, target)
      if (!res.body) throw new Error('流式响应为空')
      const reader = res.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buf = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        // SSE 事件以双换行分隔
        const events = buf.split('\n\n')
        buf = events.pop() || ''
        for (const ev of events) {
          const line = ev.trim()
          if (!line.startsWith('data:')) continue
          const json = line.slice(5).trim()
          if (!json) continue
          try {
            const obj = JSON.parse(json)
            setMigrateProgress((prev) => {
              if (!prev) return prev
              const next = { ...prev, perFile: { ...prev.perFile } }
              if (obj.type === 'start') {
                next.current = obj.doc_id
              } else if (obj.type === 'done') {
                next.done = (next.done || 0) + 1
                next.current = null
                next.perFile[obj.doc_id] = { ok: true, title: obj.title, chunks: obj.chunks_updated }
              } else if (obj.type === 'error') {
                next.failed = (next.failed || 0) + 1
                next.failedIds = [...(next.failedIds || []), obj.doc_id]
                next.current = null
                next.perFile[obj.doc_id] = { ok: false, error: obj.error }
              } else if (obj.type === 'summary') {
                next.summary = obj
                next.running = false
              } else if (obj.type === 'done' && !obj.index && obj.index !== 0) {
                // 服务端 done
                next.running = false
              }
              return next
            })
          } catch (e) {
            console.warn('SSE 解析失败:', json)
          }
        }
      }
      // 迁移完成后刷新数据（即使有失败项）
      setSelectedDocs(new Set())
      loadData()
    } catch (e: any) {
      alert('迁移失败: ' + (e.message || 'unknown'))
      setMigrateProgress((p) => p ? { ...p, running: false } : p)
    }
  }

  // 任务 2.2：仅重试失败的文件（直接调 SSE，不重开 dialog）
  const handleRetryFailed = async () => {
    if (!migrateProgress?.failedIds?.length || !migrateDialog?.target) {
      // 兜底：若 dialog 已关闭，从 progress 内的 target 记录取
      return
    }
    const failedIds = migrateProgress.failedIds
    const target = migrateDialog.target
    // 重置进度态进入新一轮
    setMigrateProgress({
      running: true, total: failedIds.length, done: 0, failed: 0,
      current: null, failedIds: [], perFile: {}, summary: null,
    })
    try {
      const res = await documentApi.migrateBatchStream(failedIds, target)
      if (!res.body) throw new Error('流式响应为空')
      const reader = res.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buf = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const events = buf.split('\n\n')
        buf = events.pop() || ''
        for (const ev of events) {
          const line = ev.trim()
          if (!line.startsWith('data:')) continue
          const json = line.slice(5).trim()
          if (!json) continue
          try {
            const obj = JSON.parse(json)
            setMigrateProgress((prev) => {
              if (!prev) return prev
              const next = { ...prev, perFile: { ...prev.perFile } }
              if (obj.type === 'start') {
                next.current = obj.doc_id
              } else if (obj.type === 'done') {
                next.done = (next.done || 0) + 1
                next.current = null
                next.perFile[obj.doc_id] = { ok: true, title: obj.title, chunks: obj.chunks_updated }
              } else if (obj.type === 'error') {
                next.failed = (next.failed || 0) + 1
                next.failedIds = [...(next.failedIds || []), obj.doc_id]
                next.current = null
                next.perFile[obj.doc_id] = { ok: false, error: obj.error }
              } else if (obj.type === 'summary') {
                next.summary = obj
                next.running = false
              }
              return next
            })
          } catch (e) { /* ignore */ }
        }
      }
      loadData()
    } catch (e: any) {
      alert('重试失败: ' + (e.message || 'unknown'))
      setMigrateProgress((p) => p ? { ...p, running: false } : p)
    }
  }

  return (
    <div className="space-y-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">文档管理</h1>
          <p className="text-sm text-gray-500 mt-1">管理知识库文档，支持批量操作</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowRecycle(!showRecycle)}
            className="flex items-center gap-2 px-4 py-2.5 bg-gray-100 text-gray-700 rounded-xl hover:bg-gray-200 transition-all"
          >
            <RotateCcw className="h-4 w-4" />
            <span>回收站</span>
          </button>
          <button
            onClick={() => setShowUpload(!showUpload)}
            className="flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-blue-500 to-indigo-600 text-white rounded-xl hover:shadow-lg transition-all"
          >
            <Upload className="h-4 w-4" />
            <span>上传文档</span>
          </button>
        </div>
      </div>

      {/* 回收站页面（覆盖式） */}
      {showRecycle && (
        <RecycleBinPage
          onClose={() => setShowRecycle(false)}
          onRestored={() => loadData()}
        />
      )}

      {/* 任务 P0-4：版本历史 Modal */}
      <DocumentVersionModal
        docId={versionDocId || ''}
        open={!!versionDocId}
        onClose={() => setVersionDocId(null)}
        onRolledBack={() => loadData()}
      />

      {/* 上传区域 */}
      {showUpload && (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-gray-900">上传新文档</h3>
            <button
              onClick={() => setShowUpload(false)}
              className="p-1 hover:bg-gray-100 rounded-lg transition-colors"
            >
              <X className="h-4 w-4 text-gray-400" />
            </button>
          </div>
          <DragUpload onUploadSuccess={() => { setShowUpload(false); loadData() }} />
        </div>
      )}

      {/* 工具栏 */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4">
        <div className="flex flex-wrap items-center gap-3">
          {/* 任务 P1-2 / T2：标签筛选 */}
          {selectedTags.length > 0 && (
            <div className="w-full mb-2">
              <TagPicker selected={selectedTags} onChange={setSelectedTags} />
            </div>
          )}
          {/* 搜索 */}
          <div className="flex-1 min-w-[200px] relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索文档..."
              className="w-full pl-10 pr-10 py-2.5 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 text-sm"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-full hover:bg-gray-200 transition-colors"
                title="清空搜索"
              >
                <X className="h-3.5 w-3.5 text-gray-400" />
              </button>
            )}
          </div>

          {/* 分类筛选（直接显示在下方的"按分类分组"视图里选） */}
          <div className="relative">
            <button
              onClick={() => setSelectedTags(selectedTags.length > 0 ? [] : [...selectedTags, ''])}
              className="px-3 py-2.5 border border-gray-200 rounded-xl text-sm hover:bg-gray-50"
            >
              标签 {selectedTags.length > 0 && <span className="ml-1 text-blue-600">({selectedTags.length})</span>}
            </button>
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
              className="appearance-none pl-4 pr-10 py-2.5 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 text-sm bg-white"
            >
              <option value="">全部分类</option>
              {categories.map(cat => (
                <option key={cat.name} value={cat.name}>{cat.name}</option>
              ))}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
          </div>

          {/* 新建分类按钮（直接在文档管理页内联） */}
          <button
            onClick={() => setNewCategory({ name: '', strategy: 'recursive', chunk_size: 500, overlap: 100 })}
            className="flex items-center gap-1.5 px-3 py-2.5 bg-blue-50 text-blue-600 rounded-xl hover:bg-blue-100 transition-colors text-sm font-medium"
            title="新建分类"
          >
            <FolderPlus className="h-4 w-4" />
            <span>新建分类</span>
          </button>

          {/* 批量操作 */}
          {selectedDocs.size > 0 && (
            <>
              {/* 任务 4：批量迁移 */}
              <button
                onClick={() => openMigrateDialog(Array.from(selectedDocs))}
                className="flex items-center gap-2 px-4 py-2.5 bg-indigo-50 text-indigo-600 rounded-xl hover:bg-indigo-100 transition-colors text-sm font-medium"
              >
                <FolderInput className="h-4 w-4" />
                <span>迁移选中 ({selectedDocs.size})</span>
              </button>
              <button
                onClick={handleBatchDelete}
                className="flex items-center gap-2 px-4 py-2.5 bg-red-50 text-red-600 rounded-xl hover:bg-red-100 transition-colors text-sm font-medium"
              >
                <Trash2 className="h-4 w-4" />
                <span>删除选中 ({selectedDocs.size})</span>
              </button>
            </>
          )}

          {/* 任务 4.3：操作日志入口 */}
          <button
            onClick={() => setOpLogOpen(true)}
            className="flex items-center gap-1.5 px-3 py-2.5 bg-gray-50 text-gray-600 rounded-xl hover:bg-gray-100 transition-colors text-sm"
            title="查看文档迁移操作日志"
          >
            <History className="h-4 w-4" />
            <span>迁移日志</span>
          </button>

          {/* 视图模式切换 */}
          <div className="flex items-center bg-gray-100 rounded-xl p-1">
            <button
              onClick={() => setViewMode('grouped')}
              className={`p-1.5 rounded-lg transition-colors ${
                viewMode === 'grouped' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
              title="按分类分组"
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`p-1.5 rounded-lg transition-colors ${
                viewMode === 'list' ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
              title="列表视图"
            >
              <ListIcon className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {/* 文档视图 - grouped（按分类）/ list（列表）/ drill-down（分类下钻） */}
      {drillCategory ? (
        <CategoryDetailView
          categoryName={drillCategory}
          documents={documents.filter((d) => d.category === drillCategory)}
          onBack={() => setDrillCategory(null)}
          onView={setSelectedDoc}
          onDelete={handleDelete}
          onMigrate={openMigrateDialog}
        />
      ) : viewMode === 'grouped' ? (
        <GroupedDocumentsView
          groupedDocs={groupedDocs}
          categories={categories}
          loading={loading}
          searchQuery={searchQuery}
          onView={setSelectedDoc}
          onDelete={handleDelete}
          onChangeCategory={handleChangeDocCategory}
          onEditCategory={setEditingCategory}
          onDeleteCategory={handleDeleteCategory}
          onAddNewCategory={() => setNewCategory({ name: '', strategy: 'recursive', chunk_size: 500, overlap: 100 })}
          onEnterCategory={setDrillCategory}
        />
      ) : (
        <ListDocumentsView
          docs={filteredDocs}
          loading={loading}
          selectedDocs={selectedDocs}
          toggleSelect={toggleSelect}
          toggleSelectAll={toggleSelectAll}
          categories={categories}
          onView={setSelectedDoc}
          onDelete={handleDelete}
          onChangeCategory={handleChangeDocCategory}
        />
      )}

      {/* 文档详情弹窗 */}
      {selectedDoc && (
        <DocumentDetail
          document={selectedDoc}
          onClose={() => setSelectedDoc(null)}
        />
      )}

      {/* 内联：新建分类表单（直接在文档管理页面里，不弹窗） */}
      {newCategory && (
        <CategoryEditPanel
          category={newCategory}
          isNew
          onChange={setNewCategory}
          onSave={() => handleSaveCategory(newCategory, true)}
          onCancel={() => setNewCategory(null)}
        />
      )}

      {/* 内联：编辑现有分类 */}
      {editingCategory && (
        <CategoryEditPanel
          category={editingCategory}
          isNew={false}
          onChange={setEditingCategory}
          onSave={() => handleSaveCategory(editingCategory, false)}
          onCancel={() => setEditingCategory(null)}
        />
      )}

      {/* 任务 4：迁移二次确认弹窗 */}
      {migrateDialog && (
        <MigrateDialog
          ids={migrateDialog.ids}
          documents={documents}
          categories={categories}
          target={migrateDialog.target}
          onChangeTarget={(t) => setMigrateDialog({ ...migrateDialog, target: t })}
          onCancel={() => setMigrateDialog(null)}
          onConfirm={handleConfirmMigrate}
        />
      )}

      {/* 任务 4.3：操作日志面板 */}
      {opLogOpen && <OpLogPanel onClose={() => setOpLogOpen(false)} />}

      {/* 任务 2.2：迁移进度 + 失败重试弹窗 */}
      {migrateProgress && (
        <MigrateProgressDialog
          progress={migrateProgress}
          target={migrateDialog?.target || ''}
          onRetry={handleRetryFailed}
          onClose={() => setMigrateProgress(null)}
        />
      )}
    </div>
  )
}

// ==================== 子组件：按分类分组视图 ====================

interface GroupedViewProps {
  groupedDocs: Map<string, Document[]>
  categories: Category[]
  loading: boolean
  searchQuery: string
  onView: (doc: Document) => void
  onDelete: (id: string) => void
  onChangeCategory: (docId: string, cat: string) => void
  onEditCategory: (cat: Category) => void
  onDeleteCategory: (name: string) => void
  onAddNewCategory: () => void
  onEnterCategory: (catName: string) => void
}

function GroupedDocumentsView({
  groupedDocs, categories, loading,
  onEditCategory, onDeleteCategory, onAddNewCategory,
  onEnterCategory,
}: GroupedViewProps) {
  if (loading) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-12 text-center">
        <Loader2 className="h-6 w-6 animate-spin mx-auto text-blue-500" />
        <p className="text-sm text-gray-400 mt-2">加载中...</p>
      </div>
    )
  }

  // 把"声明但无文档"的分类也展示出来（空分组）
  const allCategories = useMemo(() => {
    const names = new Set<string>()
    categories.forEach((c) => names.add(c.name))
    groupedDocs.forEach((_, k) => names.add(k))
    return Array.from(names)
  }, [categories, groupedDocs])

  if (allCategories.length === 0) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-12 text-center text-gray-400">
        <FolderTree className="h-12 w-12 mx-auto mb-3 text-gray-200" />
        <p className="text-sm">暂无分类，点击上方"新建分类"开始</p>
        <button
          onClick={onAddNewCategory}
          className="mt-3 px-3 py-1.5 bg-blue-50 text-blue-600 rounded-lg text-sm"
        >
          新建第一个分类
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {/* v2 需求 4：响应式卡片网格
          移动端 1 列(sm: 2) | 平板 3 列(md: 3) | 桌面 4 列(lg: 4) | 大屏 5 列(xl: 5) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
        {allCategories.map((catName) => {
          const docs = groupedDocs.get(catName) || []
          const catInfo = categories.find((c) => c.name === catName)
          const isDefault = catName === '默认'
          return (
            <div
              key={catName}
              className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden hover:shadow-md transition-shadow"
            >
              <div className="px-4 py-3 bg-gradient-to-br from-blue-50 to-indigo-50 border-b border-gray-100">
                <div className="flex items-center gap-2">
                  <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-white font-bold shadow-sm">
                    {catName.substring(0, 1)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <h3 className="font-semibold text-gray-900 text-sm truncate">{catName}</h3>
                      {isDefault && <span className="px-1 py-0.5 bg-gray-200 text-gray-600 text-[10px] rounded flex-shrink-0">默认</span>}
                    </div>
                    <p className="text-[11px] text-gray-500 mt-0.5">
                      {docs.length} 篇 · {catInfo?.strategy || '默认策略'}
                    </p>
                  </div>
                  <div className="flex flex-col gap-0.5">
                    {catInfo && (
                      <button
                        onClick={() => onEditCategory(catInfo)}
                        className="p-1 text-gray-400 hover:text-blue-600 hover:bg-white rounded"
                        title="编辑分类"
                      >
                        <Edit3 className="h-3 w-3" />
                      </button>
                    )}
                    {!isDefault && catInfo && (
                      <button
                        onClick={() => onDeleteCategory(catName)}
                        className="p-1 text-gray-400 hover:text-red-500 hover:bg-white rounded"
                        title="删除分类"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {/* 缩略图（首篇文档标题作为封面替代）*/}
              <div className="aspect-video bg-gradient-to-br from-gray-50 to-gray-100 flex items-center justify-center">
                {docs.length > 0 ? (
                  <div className="text-center px-3">
                    <FileText className="h-8 w-8 mx-auto text-blue-400 mb-1" />
                    <p className="text-xs text-gray-500 truncate">{docs[0].title}</p>
                  </div>
                ) : (
                  <div className="text-center">
                    <FileText className="h-8 w-8 mx-auto text-gray-300 mb-1" />
                    <p className="text-xs text-gray-400">暂无文档</p>
                  </div>
                )}
              </div>

              <div className="px-4 py-2 text-center">
                <button
                  onClick={() => onEnterCategory(catName)}
                  className="text-xs text-blue-600 hover:underline"
                >
                  进入分类 ({docs.length}) →
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ==================== 子组件：分类下钻详情视图 ====================

interface CategoryDetailViewProps {
  categoryName: string
  documents: Document[]
  onBack: () => void
  onView: (doc: Document) => void
  onDelete: (id: string) => void
  onMigrate: (ids: string[]) => void
}

function CategoryDetailView({
  categoryName, documents, onBack, onView, onDelete, onMigrate,
}: CategoryDetailViewProps) {
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set())

  const toggleSelect = (id: string) => {
    const n = new Set(selectedDocs)
    n.has(id) ? n.delete(id) : n.add(id)
    setSelectedDocs(n)
  }

  const toggleSelectAll = () => {
    if (selectedDocs.size === documents.length) setSelectedDocs(new Set())
    else setSelectedDocs(new Set(documents.map((d) => d.id)))
  }

  const handleDownload = (doc: Document) => {
    // 通过后端 /api/documents/{id}/raw?download=1 拉取并保存原始文件
    // （替代旧版用 doc.content 文本打包成 Blob 的方式——保证下载的是上传时的真实原始文件）
    const a = document.createElement('a')
    a.href = `/api/documents/${doc.id}/raw?download=1`
    a.download = doc.filename || doc.title
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  const handleBatchDownload = () => {
    const selected = documents.filter((d) => selectedDocs.has(d.id))
    if (selected.length === 1) {
      handleDownload(selected[0])
    } else {
      // 串行触发，避免浏览器并发下载限制
      selected.forEach((doc, i) => {
        setTimeout(() => handleDownload(doc), i * 300)
      })
    }
  }

  return (
    <div className="space-y-4">
      {/* 返回栏 */}
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 bg-white border border-gray-200 rounded-lg"
        >
          <ArrowLeft className="h-4 w-4" />
          返回分类列表
        </button>
        <div>
          <span className="text-lg font-semibold text-gray-900">{categoryName}</span>
          <span className="ml-2 text-sm text-gray-400">({documents.length} 篇文档)</span>
        </div>
        {selectedDocs.size > 0 && (
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => onMigrate(Array.from(selectedDocs))}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-indigo-50 text-indigo-600 rounded-lg hover:bg-indigo-100"
              title="迁移到其他分类"
            >
              <FolderInput className="h-3.5 w-3.5" />
              迁移选中 ({selectedDocs.size})
            </button>
            <button
              onClick={handleBatchDownload}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-blue-50 text-blue-600 rounded-lg hover:bg-blue-100"
            >
              <Download className="h-3.5 w-3.5" />
              下载选中 ({selectedDocs.size})
            </button>
          </div>
        )}
      </div>

      {/* 文档列表 */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
        {documents.length === 0 ? (
          <div className="p-12 text-center text-gray-400">
            <FileText className="h-12 w-12 mx-auto mb-3 text-gray-200" />
            <p>该分类下暂无文档</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
                <tr>
                  <th className="px-4 py-3 w-12">
                    <input
                      type="checkbox"
                      checked={documents.length > 0 && selectedDocs.size === documents.length}
                      onChange={toggleSelectAll}
                      className="rounded border-gray-300 text-blue-600"
                    />
                  </th>
                  <th className="px-4 py-3 text-left">文档名称</th>
                  <th className="px-4 py-3 text-left">上传时间</th>
                  <th className="px-4 py-3 text-left">分块数</th>
                  <th className="px-4 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {documents.map((doc) => (
                  <tr key={doc.id} className="hover:bg-gray-50/80 group">
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selectedDocs.has(doc.id)}
                        onChange={() => toggleSelect(doc.id)}
                        className="rounded border-gray-300 text-blue-600"
                      />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <FileText className="h-4 w-4 text-blue-500 flex-shrink-0" />
                        <span className="font-medium text-gray-900 text-sm">{doc.title}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {new Date(doc.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {doc.chunk_count || '-'}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => onView(doc)}
                          className="p-2 hover:bg-gray-100 rounded-lg"
                          title="在线预览"
                        >
                          <Eye className="h-4 w-4 text-gray-400" />
                        </button>
                        <button
                          onClick={() => onMigrate([doc.id])}
                          className="p-2 hover:bg-indigo-50 rounded-lg"
                          title="迁移至其他分类"
                        >
                          <FolderInput className="h-4 w-4 text-indigo-500" />
                        </button>
                        <button
                          onClick={() => handleDownload(doc)}
                          className="p-2 hover:bg-blue-50 rounded-lg"
                          title="下载原始文件"
                        >
                          <Download className="h-4 w-4 text-blue-500" />
                        </button>
                        <button
                          onClick={() => setVersionDocId(doc.id)}
                          className="p-2 hover:bg-amber-50 rounded-lg"
                          title="版本历史"
                        >
                          <History className="h-4 w-4 text-amber-500" />
                        </button>
                        <button
                          onClick={() => onDelete(doc.id)}
                          className="p-2 hover:bg-red-50 rounded-lg"
                          title="删除"
                        >
                          <Trash2 className="h-4 w-4 text-red-400" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ==================== 子组件：列表视图 ====================

interface ListViewProps {
  docs: Document[]
  loading: boolean
  selectedDocs: Set<string>
  toggleSelect: (id: string) => void
  toggleSelectAll: () => void
  categories: Category[]
  onView: (doc: Document) => void
  onDelete: (id: string) => void
  onChangeCategory: (docId: string, cat: string) => void
}

function ListDocumentsView({
  docs, loading, selectedDocs, toggleSelect, toggleSelectAll, categories, onView, onDelete, onChangeCategory,
}: ListViewProps) {
  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-100">
              <th className="px-4 py-3 w-12">
                <input
                  type="checkbox"
                  checked={docs.length > 0 && selectedDocs.size === docs.length}
                  onChange={toggleSelectAll}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">文档名称</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">分类</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">上传时间</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">分块数</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center">
                  <Loader2 className="h-6 w-6 animate-spin mx-auto text-blue-500" />
                </td>
              </tr>
            ) : docs.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-gray-400">
                  <FileText className="h-12 w-12 mx-auto mb-3 text-gray-200" />
                  <p className="text-sm">暂无文档</p>
                </td>
              </tr>
            ) : (
              docs.map((doc) => (
                <tr key={doc.id} className="hover:bg-gray-50/80 transition-colors group">
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selectedDocs.has(doc.id)}
                      onChange={() => toggleSelect(doc.id)}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center">
                        <FileText className="h-4 w-4 text-blue-500" />
                      </div>
                      <span className="font-medium text-gray-900 text-sm">{doc.title}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <select
                      defaultValue={doc.category}
                      onChange={(e) => onChangeCategory(doc.id, e.target.value)}
                      className="text-xs px-2 py-1 border border-gray-200 rounded bg-white"
                    >
                      {categories.map((c) => (
                        <option key={c.name} value={c.name}>{c.name}</option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {new Date(doc.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {doc.chunk_count || '-'}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => onView(doc)}
                        className="p-2 hover:bg-gray-100 rounded-lg"
                        title="查看详情"
                      >
                        <Eye className="h-4 w-4 text-gray-400" />
                      </button>
                      <button
                        onClick={() => onDelete(doc.id)}
                        className="p-2 hover:bg-red-50 rounded-lg"
                        title="删除"
                      >
                        <Trash2 className="h-4 w-4 text-red-400" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ==================== 子组件：分类编辑面板 ====================

interface CategoryEditPanelProps {
  category: Category
  isNew: boolean
  onChange: (c: Category) => void
  onSave: () => void
  onCancel: () => void
}

function CategoryEditPanel({ category, isNew, onChange, onSave, onCancel }: CategoryEditPanelProps) {
  return (
    <div className="bg-white rounded-2xl shadow-sm border-2 border-blue-200 p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          {isNew ? <Plus className="h-5 w-5 text-blue-500" /> : <Edit3 className="h-5 w-5 text-blue-500" />}
          {isNew ? '新建分类' : `编辑分类：${category.name}`}
        </h3>
        <button onClick={onCancel} className="p-1 hover:bg-gray-100 rounded-lg">
          <X className="h-4 w-4 text-gray-400" />
        </button>
      </div>
      {/* 简化：保留原始编辑表单的内容（策略、chunk_size、overlap） */}
      <CategoryForm
        category={category}
        onChange={onChange}
      />
      <div className="flex gap-2 justify-end">
        <button onClick={onCancel} className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 text-sm">取消</button>
        <button onClick={onSave} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm">保存</button>
      </div>
    </div>
  )
}

// ==================== 任务 4：迁移二次确认弹窗 ====================

interface MigrateDialogProps {
  ids: string[]
  documents: Document[]
  categories: Category[]
  target: string
  onChangeTarget: (t: string) => void
  onCancel: () => void
  onConfirm: () => void
}

function MigrateDialog({ ids, documents, categories, target, onChangeTarget, onCancel, onConfirm }: MigrateDialogProps) {
  const idSet = new Set(ids)
  const targets = documents.filter((d) => idSet.has(d.id))
  // 排除已选文档当前的分类
  const currentCategories = Array.from(new Set(targets.map((d) => d.category)))
  const candidateCategories = categories.filter((c) => !currentCategories.includes(c.name))

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
      }}
      onClick={onCancel}
    >
      <div
        style={{ background: '#fff', borderRadius: 12, width: '100%', maxWidth: 520, padding: 24 }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
          <FolderInput className="h-5 w-5 text-indigo-500" />
          迁移文档到新分类
        </h3>
        <p style={{ marginTop: 8, color: '#64748b', fontSize: 13 }}>
          本次将迁移 <b>{ids.length}</b> 篇文档。原分类：
          {currentCategories.map((c) => (
            <span key={c} style={{ display: 'inline-block', marginLeft: 4, padding: '2px 6px', background: '#f1f5f9', borderRadius: 4, fontSize: 12 }}>{c}</span>
          ))}
        </p>
        <div style={{ marginTop: 16 }}>
          <label style={{ display: 'block', fontSize: 13, color: '#475569', marginBottom: 6 }}>选择目标分类</label>
          <select
            value={target}
            onChange={(e) => onChangeTarget(e.target.value)}
            style={{
              width: '100%', padding: '8px 12px', border: '1px solid #e2e8f0',
              borderRadius: 8, fontSize: 14, background: '#fff',
            }}
          >
            <option value="">— 请选择 —</option>
            {candidateCategories.map((c) => (
              <option key={c.name} value={c.name}>{c.name}</option>
            ))}
            <option value="__new__">+ 新建分类…</option>
          </select>
          {target === '__new__' && (
            <input
              autoFocus
              placeholder="输入新分类名称"
              onChange={(e) => onChangeTarget(e.target.value.trim())}
              style={{
                marginTop: 8, width: '100%', padding: '8px 12px',
                border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 14,
              }}
            />
          )}
        </div>
        <div style={{ marginTop: 12, padding: 12, background: '#fef3c7', borderRadius: 8, fontSize: 12, color: '#92400e' }}>
          ⚠️ 迁移操作将同步更新向量数据库中的检索元数据，且不可撤销。确认无误后再点击「确认迁移」。
        </div>
        <div style={{ marginTop: 16, display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button
            onClick={onCancel}
            style={{ padding: '8px 16px', background: '#f1f5f9', color: '#475569', borderRadius: 8, fontSize: 14 }}
          >
            取消
          </button>
          <button
            disabled={!target || target === '__new__'}
            onClick={onConfirm}
            style={{
              padding: '8px 16px',
              background: (!target || target === '__new__') ? '#cbd5e1' : '#4f46e5',
              color: '#fff', borderRadius: 8, fontSize: 14, cursor: (!target || target === '__new__') ? 'not-allowed' : 'pointer',
            }}
          >
            确认迁移
          </button>
        </div>
      </div>
    </div>
  )
}

// ==================== 任务 4.3：迁移操作日志面板 ====================
function OpLogPanel({ onClose }: { onClose: () => void }) {
  const [logs, setLogs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    documentApi.getOpLog(50).then((r) => {
      setLogs(r.data || [])
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', justifyContent: 'flex-end' }}
      onClick={onClose}
    >
      <div
        style={{ background: '#fff', width: '100%', maxWidth: 560, height: '100%', overflow: 'auto', padding: 24 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
            <History className="h-5 w-5 text-gray-500" />
            文档迁移操作日志
          </h3>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded-lg">
            <X className="h-4 w-4 text-gray-400" />
          </button>
        </div>
        {loading ? (
          <p style={{ color: '#94a3b8' }}>加载中...</p>
        ) : logs.length === 0 ? (
          <p style={{ color: '#94a3b8' }}>暂无操作记录</p>
        ) : (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {logs.map((l, i) => (
              <li key={i} style={{ borderBottom: '1px solid #f1f5f9', padding: '10px 0' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                  <span style={{
                    padding: '2px 6px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                    background: l.action === 'migrate_batch' ? '#e0e7ff' : '#dbeafe',
                    color: l.action === 'migrate_batch' ? '#4338ca' : '#1d4ed8',
                  }}>
                    {l.action === 'migrate_batch' ? '批量' : '单篇'}
                  </span>
                  <span style={{ color: '#64748b' }}>{l.time}</span>
                  <span style={{ color: '#94a3b8' }}>·</span>
                  <span style={{ color: '#64748b' }}>操作人：{l.operator}</span>
                </div>
                <div style={{ marginTop: 4, fontSize: 13, color: '#334155' }}>
                  {l.action === 'migrate_batch'
                    ? `批量迁移 ${l.migrated_count} 个文档到「${l.target}」（更新 ${l.chunks_updated} 个分块）`
                    : `「${l.from}」→「${l.to}」（更新 ${l.chunks_updated} 个分块）`}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

// 分类编辑表单（保留原行为）
function CategoryForm({ category, onChange }: { category: Category; onChange: (c: Category) => void }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div>
        <label className="text-xs text-gray-500">分类名称</label>
        <input
          value={category.name}
          onChange={(e) => onChange({ ...category, name: e.target.value })}
          className="mt-1 w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
          disabled={!category.id && category.name === '' /* newCategory mode允许编辑 */}
        />
      </div>
      <div>
        <label className="text-xs text-gray-500">分块策略</label>
        <select
          value={category.strategy}
          onChange={(e) => onChange({ ...category, strategy: e.target.value })}
          className="mt-1 w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white"
        >
          {STRATEGY_OPTIONS.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
      </div>
      <div>
        <label className="text-xs text-gray-500">chunk_size</label>
        <input
          type="number"
          value={category.chunk_size || 500}
          onChange={(e) => onChange({ ...category, chunk_size: Number(e.target.value) })}
          className="mt-1 w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
        />
      </div>
      <div>
        <label className="text-xs text-gray-500">overlap</label>
        <input
          type="number"
          value={category.overlap || 100}
          onChange={(e) => onChange({ ...category, overlap: Number(e.target.value) })}
          className="mt-1 w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
        />
      </div>
    </div>
  )
}

// ==================== 任务 2.2：迁移进度 + 失败重试弹窗 ====================
function MigrateProgressDialog({
  progress, target, onRetry, onClose,
}: {
  progress: {
    running: boolean; total: number; done: number; failed: number
    current: string | null; failedIds: string[]
    perFile: Record<string, { ok: boolean; title?: string; chunks?: number; error?: string }>
    summary: any | null
  }
  target: string
  onRetry: () => void
  onClose: () => void
}) {
  const percent = progress.total > 0
    ? Math.round(((progress.done + progress.failed) / progress.total) * 100)
    : 0
  const fileEntries = Object.entries(progress.perFile)

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1100,
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}
      onClick={progress.running ? undefined : onClose}
    >
      <div
        style={{ background: '#fff', borderRadius: 12, width: '100%', maxWidth: 560,
          padding: 24, maxHeight: '85vh', display: 'flex', flexDirection: 'column' }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
          <FolderInput className="h-5 w-5 text-indigo-500" />
          迁移进度 →「{target}」
        </h3>

        {/* 进度条 */}
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#475569', marginBottom: 6 }}>
            <span>
              {progress.running ? '迁移中...' : '迁移完成'}
              {progress.current && <span style={{ color: '#6366f1' }}> · 正在处理 {progress.current.slice(0, 8)}...</span>}
            </span>
            <span>
              {progress.done + progress.failed} / {progress.total} ({percent}%)
            </span>
          </div>
          <div style={{ height: 8, background: '#e2e8f0', borderRadius: 4, overflow: 'hidden' }}>
            <div style={{
              width: percent + '%', height: '100%',
              background: progress.failed > 0
                ? 'linear-gradient(90deg, #10b981 0%, #ef4444 100%)'
                : '#10b981',
              transition: 'width 200ms ease',
            }} />
          </div>
          <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 12 }}>
            <span style={{ color: '#10b981' }}>✓ 成功 {progress.done}</span>
            <span style={{ color: '#ef4444' }}>✗ 失败 {progress.failed}</span>
          </div>
        </div>

        {/* 文件列表（最多展示前 50） */}
        <div style={{ marginTop: 16, flex: 1, overflow: 'auto', border: '1px solid #f1f5f9', borderRadius: 8, padding: 8, background: '#fafbfc' }}>
          {fileEntries.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#94a3b8', fontSize: 12, padding: 12 }}>等待处理...</div>
          ) : (
            fileEntries.slice(-50).map(([id, info]) => (
              <div key={id} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 6px', fontSize: 12 }}>
                {info.ok ? (
                  <span style={{ color: '#10b981' }}>✓</span>
                ) : (
                  <span style={{ color: '#ef4444' }}>✗</span>
                )}
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {info.title || id.slice(0, 16)}
                </span>
                {info.chunks !== undefined && (
                  <span style={{ color: '#94a3b8', fontSize: 11 }}>{info.chunks} chunks</span>
                )}
                {info.error && (
                  <span style={{ color: '#ef4444', fontSize: 11 }} title={info.error}>{info.error.slice(0, 20)}</span>
                )}
              </div>
            ))
          )}
        </div>

        {/* 按钮区 */}
        <div style={{ marginTop: 16, display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          {progress.failed > 0 && !progress.running && (
            <button
              onClick={onRetry}
              style={{ padding: '8px 16px', background: '#f59e0b', color: '#fff', borderRadius: 8, fontSize: 14, fontWeight: 500 }}
            >
              重试失败项 ({progress.failed})
            </button>
          )}
          <button
            disabled={progress.running}
            onClick={onClose}
            style={{
              padding: '8px 16px',
              background: progress.running ? '#cbd5e1' : '#3b82f6',
              color: '#fff', borderRadius: 8, fontSize: 14, fontWeight: 500,
              cursor: progress.running ? 'not-allowed' : 'pointer',
            }}
          >
            {progress.running ? '迁移中...' : '完成'}
          </button>
        </div>
      </div>
    </div>
  )
}
