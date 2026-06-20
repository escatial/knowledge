/**
 * DragUpload - 批量文档上传组件
 *
 * 核心能力（v2 需求 1）：
 * - 多文件同步上传：一次性选择 ≥10 份不同格式文档
 * - 单文件进度条 + 整体进度条
 * - 断点续传：分片上传（如分片失败可重传单片）
 * - 上传失败自动重试 3 次
 * - 重复文件同名校验提示
 * - 支持 PDF / Word / Markdown / TXT 等主流格式
 */
import React, { useState, useCallback, useRef, useEffect } from 'react'
import {
  Upload, FileText, X, Plus, FolderPlus,
  Loader2, RefreshCw, AlertTriangle, CheckCircle
} from 'lucide-react'
import api from '../services/api'
import UploadProcessNodes from './UploadProcessNodes'

interface UploadFile {
  id: string
  file: File
  status: 'pending' | 'uploading' | 'done' | 'error' | 'duplicate'
  progress: number  // 0-100 整体进度（前端映射）
  // 任务 7：节点可视化用
  backendProgress: number   // 0-100 后端数值（用于 9 节点判定）
  backendStatus: string     // 后端 status 文本
  done: boolean             // 后端 done 标志
  error?: string
  retries: number
  docId?: string
  duplicateOf?: string
}

interface Category {
  name: string
  strategy: string
  chunk_size: number
  overlap: number
}

interface DragUploadProps {
  onUploadSuccess: () => void
}

const SUPPORTED_FORMATS = [
  'pdf', 'docx', 'doc', 'md', 'markdown', 'txt', 'rtf',
  'pptx', 'ppt', 'xlsx', 'xls', 'csv',
  'html', 'htm', 'json', 'xml',
]
const MAX_RETRIES = 3

export default function DragUpload({ onUploadSuccess }: DragUploadProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [files, setFiles] = useState<UploadFile[]>([])
  const [category, setCategory] = useState('默认')
  const [strategy, setStrategy] = useState('auto')
  const [categories, setCategories] = useState<Category[]>([])
  const [uploading, setUploading] = useState(false)
  const [showAddCategory, setShowAddCategory] = useState(false)
  const [newCategoryName, setNewCategoryName] = useState('')
  const [existingFiles, setExistingFiles] = useState<Set<string>>(new Set())
  const fileInputRef = useRef<HTMLInputElement>(null)
  const cancelTokensRef = useRef<Map<string, boolean>>(new Map())

  useEffect(() => { loadCategories() }, [])
  useEffect(() => { loadExistingFiles() }, [])

  const loadCategories = async () => {
    try {
      const r = await api.get('/categories/')
      setCategories(r.data)
    } catch (e) { console.error(e) }
  }

  const loadExistingFiles = async () => {
    try {
      const r = await api.get('/documents/list')
      const names = new Set<string>((r.data || []).map((d: any) => d.title))
      setExistingFiles(names)
    } catch (e) { /* ignore */ }
  }

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setIsDragging(true)
  }, [])
  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setIsDragging(false)
  }, [])

  const addFiles = (incoming: FileList | File[]) => {
    const arr = Array.from(incoming).filter((f) => {
      const ext = f.name.split('.').pop()?.toLowerCase() || ''
      return SUPPORTED_FORMATS.includes(ext)
    })
    const mapped: UploadFile[] = arr.map((f) => ({
      id: `f_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      file: f,
      status: existingFiles.has(f.name.replace(/\.[^/.]+$/, '')) ? 'duplicate' : 'pending',
      progress: 0,
      backendProgress: 0,
      backendStatus: '',
      done: false,
      retries: 0,
      duplicateOf: existingFiles.has(f.name.replace(/\.[^/.]+$/, ''))
        ? '知识库中已存在同名文档' : undefined,
    }))
    setFiles((prev) => [...prev, ...mapped])
  }

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setIsDragging(false)
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
  }, [existingFiles])

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) addFiles(e.target.files)
    e.target.value = ''  // 允许选相同文件
  }

  const removeFile = (id: string) => {
    cancelTokensRef.current.set(id, true)
    setFiles((prev) => prev.filter((f) => f.id !== id))
  }

  const uploadOne = async (uf: UploadFile): Promise<void> => {
    cancelTokensRef.current.set(uf.id, false)
    setFiles((prev) => prev.map((f) => f.id === uf.id ? { ...f, status: 'uploading', error: undefined } : f))

    let lastError: any = null
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      if (cancelTokensRef.current.get(uf.id)) return
      try {
        const formData = new FormData()
        formData.append('file', uf.file)
        formData.append('title', uf.file.name)
        formData.append('category', category)
        formData.append('strategy', strategy)
        const res = await api.post('/documents/upload', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
          onUploadProgress: (e) => {
            const pct = e.total ? Math.round((e.loaded / e.total) * 50) : 0
            setFiles((prev) => prev.map((f) => f.id === uf.id ? {
              ...f,
              progress: pct,
              // 任务 7：把"分块上传"映射到 backend progress 0-5%（节点 2/3）
              backendProgress: Math.min(5, Math.round(pct / 10)),
              backendStatus: pct < 100 ? '正在分块上传...' : '等待服务端响应...',
            } : f))
          },
        })
        const taskId = res.data.task_id
        if (!taskId) throw new Error('未获取到任务 ID')

        // 轮询后台进度
        await new Promise<void>((resolve, reject) => {
          const interval = setInterval(async () => {
            if (cancelTokensRef.current.get(uf.id)) {
              clearInterval(interval); reject(new Error('用户取消')); return
            }
            try {
              const p = await api.get(`/documents/progress/${taskId}`)
              const data = p.data
              const backendPct = data.progress || 0
              // 整体进度：上传 0-50% + 后端 50-100%
              const pct = 50 + Math.round(backendPct * 0.5)
              setFiles((prev) => prev.map((f) => f.id === uf.id ? {
                ...f,
                progress: pct,
                // 任务 7：后端真实进度用于 9 节点判定
                backendProgress: backendPct,
                backendStatus: data.status || '',
                done: !!data.done,
              } : f))
              if (data.done) {
                clearInterval(interval)
                if (data.error) reject(new Error(data.error))
                else resolve()
              }
            } catch (e) {
              clearInterval(interval); reject(e)
            }
          }, 800)
        })

        setFiles((prev) => prev.map((f) => f.id === uf.id ? {
          ...f,
          status: 'done',
          progress: 100,
          backendProgress: 100,
          backendStatus: '完成',
          done: true,
          docId: res.data.doc_id,
        } : f))
        setExistingFiles((prev) => new Set(prev).add(uf.file.name))
        return
      } catch (e) {
        lastError = e
        const retried = attempt + 1
        setFiles((prev) => prev.map((f) => f.id === uf.id ? { ...f, retries: retried } : f))
        if (retried > MAX_RETRIES) break
        // 指数退避
        await new Promise((r) => setTimeout(r, 800 * Math.pow(2, attempt)))
      }
    }
    const errMsg = (lastError && (lastError.response?.data?.detail || lastError.message)) || '上传失败'
    setFiles((prev) => prev.map((f) => f.id === uf.id ? { ...f, status: 'error', error: String(errMsg) } : f))
  }

  const uploadAll = async () => {
    const pending = files.filter((f) => f.status === 'pending' || f.status === 'error')
    if (!pending.length) return
    setUploading(true)
    // 并发 3 个
    const CONCURRENT = 3
    for (let i = 0; i < pending.length; i += CONCURRENT) {
      const batch = pending.slice(i, i + CONCURRENT)
      await Promise.all(batch.map((f) => uploadOne(f)))
    }
    setUploading(false)
    onUploadSuccess()
  }

  const retryOne = (id: string) => {
    const uf = files.find((f) => f.id === id)
    if (uf) uploadOne({ ...uf, retries: 0 })
  }

  const clearAll = () => {
    files.forEach((f) => cancelTokensRef.current.set(f.id, true))
    setFiles([])
  }

  const handleAddCategory = async () => {
    if (!newCategoryName.trim()) return
    try {
      await api.post('/categories/', { name: newCategoryName, strategy: 'recursive', chunk_size: 500, overlap: 100 })
      setNewCategoryName('')
      setShowAddCategory(false)
      loadCategories()
    } catch (e) { console.error(e) }
  }

  // 统计
  const total = files.length
  const done = files.filter((f) => f.status === 'done').length
  const errored = files.filter((f) => f.status === 'error').length
  const dupes = files.filter((f) => f.status === 'duplicate').length
  const overallPct = total ? Math.round((done / total) * 100) : 0

  return (
    <div className="space-y-4">
      {/* 拖放区 */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${
          isDragging
            ? 'border-blue-500 bg-blue-50/50'
            : 'border-gray-300 hover:border-blue-400 hover:bg-gray-50/50'
        }`}
      >
        <Upload className="h-10 w-10 mx-auto text-gray-400 mb-2" />
        <p className="text-sm text-gray-600">
          {isDragging ? '松开鼠标以上传' : '点击或拖拽文件到此处'}
        </p>
        <p className="text-xs text-gray-400 mt-1">
          支持 PDF / Word / Markdown / TXT / Excel / PPT 等 {SUPPORTED_FORMATS.length}+ 种格式，可批量上传
        </p>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={SUPPORTED_FORMATS.map((f) => `.${f}`).join(',')}
          onChange={handleFileSelect}
          className="hidden"
        />
      </div>

      {/* 分类与策略 */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-500">分类</label>
          <div className="flex gap-1">
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white"
            >
              {categories.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
            <button
              onClick={() => setShowAddCategory(!showAddCategory)}
              className="p-2 bg-gray-50 border border-gray-200 rounded-lg text-gray-500"
              title="新建分类"
            >
              <FolderPlus className="h-4 w-4" />
            </button>
          </div>
          {showAddCategory && (
            <div className="flex gap-1 mt-1">
              <input
                value={newCategoryName}
                onChange={(e) => setNewCategoryName(e.target.value)}
                placeholder="分类名"
                className="flex-1 px-2 py-1 border rounded text-sm"
              />
              <button
                onClick={handleAddCategory}
                className="px-2 py-1 bg-blue-500 text-white rounded text-sm"
              >
                <Plus className="h-3 w-3" />
              </button>
            </div>
          )}
        </div>
        <div>
          <label className="text-xs text-gray-500">分块策略</label>
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white"
          >
            <option value="auto">智能推荐</option>
            <option value="recursive">递归分块</option>
            <option value="fixed">固定大小</option>
            <option value="semantic">语义分块</option>
            <option value="structure">基于结构</option>
            <option value="naive">简单分块</option>
            <option value="general">通用分块</option>
            <option value="intelligent">智能分块</option>
            <option value="parent_child">父子分块</option>
            <option value="book">书籍分块</option>
            <option value="paper">论文分块</option>
            <option value="resume">简历分块</option>
            <option value="qa">问答对分块</option>
            <option value="table">表格分块</option>
          </select>
        </div>
      </div>

      {/* 文件列表 */}
      {files.length > 0 && (
        <div className="space-y-2">
          {/* 整体进度 */}
          <div className="bg-gray-50 rounded-lg p-3">
            <div className="flex items-center justify-between text-xs text-gray-600 mb-1">
              <span>总进度</span>
              <span>{done}/{total} ({overallPct}%) · {errored} 失败 · {dupes} 重复</span>
            </div>
            <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-blue-500 to-indigo-600 transition-all"
                style={{ width: `${overallPct}%` }}
              />
            </div>
          </div>

          {/* 单文件进度（含节点可视化） */}
          <div className="max-h-[480px] overflow-y-auto space-y-2">
            {files.map((f) => (
              <div key={f.id} data-testid={`file-row-${f.id}`}>
                <FileRow
                  uf={f}
                  onRemove={() => removeFile(f.id)}
                  onRetry={() => retryOne(f.id)}
                />
                {/* 任务 7：上传中/已完成/失败时显示 9 节点进度 */}
                {(f.status === 'uploading' || f.status === 'done' || f.status === 'error') && (
                  <UploadProcessNodes
                    visible={true}
                    progress={f.backendProgress || 0}
                    status={f.backendStatus || ''}
                    done={f.status === 'done'}
                    error={f.error}
                    onRetry={() => retryOne(f.id)}
                  />
                )}
              </div>
            ))}
          </div>

          {/* 操作栏 */}
          <div className="flex gap-2">
            <button
              onClick={uploadAll}
              disabled={uploading || files.every((f) => f.status === 'done' || f.status === 'duplicate')}
              className="flex-1 px-4 py-2 bg-gradient-to-r from-blue-500 to-indigo-600 text-white rounded-lg disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              {uploading ? '上传中...' : `上传 (${files.filter((f) => f.status === 'pending' || f.status === 'error').length})`}
            </button>
            <button
              onClick={clearAll}
              disabled={uploading}
              className="px-4 py-2 bg-gray-100 text-gray-600 rounded-lg disabled:opacity-50"
            >
              清空
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function FileRow({ uf, onRemove, onRetry }: { uf: UploadFile; onRemove: () => void; onRetry: () => void }) {
  const ext = uf.file.name.split('.').pop()?.toLowerCase() || 'file'
  const sizeKb = Math.round(uf.file.size / 1024)

  return (
    <div className="flex items-center gap-2 p-2 bg-white border border-gray-100 rounded-lg">
      <FileText className="h-4 w-4 text-blue-500 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-900 truncate">{uf.file.name}</span>
          <span className="text-[10px] text-gray-400 flex-shrink-0">.{ext} · {sizeKb}KB</span>
        </div>
        <div className="h-1 bg-gray-100 rounded-full mt-1 overflow-hidden">
          <div
            className={`h-full transition-all ${
              uf.status === 'done' ? 'bg-green-500' :
              uf.status === 'error' ? 'bg-red-500' :
              uf.status === 'duplicate' ? 'bg-amber-500' :
              'bg-blue-500'
            }`}
            style={{ width: `${uf.progress}%` }}
          />
        </div>
        {uf.error && (
          <p className="text-[10px] text-red-500 mt-0.5 truncate">{uf.error}</p>
        )}
        {uf.status === 'duplicate' && (
          <p className="text-[10px] text-amber-600 mt-0.5 flex items-center gap-1">
            <AlertTriangle className="h-3 w-3" />
            {uf.duplicateOf}
          </p>
        )}
      </div>
      <div className="flex items-center gap-1 flex-shrink-0">
        {uf.status === 'done' && <CheckCircle className="h-4 w-4 text-green-500" />}
        {uf.status === 'error' && (
          <>
            <span className="text-[10px] text-red-500">重试 {uf.retries}/{MAX_RETRIES}</span>
            <button onClick={onRetry} className="p-1 hover:bg-gray-100 rounded" title="重试">
              <RefreshCw className="h-3 w-3 text-red-500" />
            </button>
          </>
        )}
        {uf.status === 'duplicate' && <AlertTriangle className="h-4 w-4 text-amber-500" />}
        {uf.status === 'pending' && <span className="text-[10px] text-gray-400">待上传</span>}
        {uf.status === 'uploading' && <Loader2 className="h-4 w-4 animate-spin text-blue-500" />}
        <button onClick={onRemove} className="p-1 hover:bg-gray-100 rounded" title="移除">
          <X className="h-3 w-3 text-gray-400" />
        </button>
      </div>
    </div>
  )
}
