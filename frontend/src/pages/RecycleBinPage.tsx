/**
 * RecycleBinPage - 文档回收站
 *
 * 需求 2：删除的文档 7 天内可恢复；恢复后自动重建图谱关联
 */
import { useState, useEffect } from 'react'
import {
  Trash2, RefreshCw, FileText, X,
  AlertTriangle, Clock, RotateCcw, ChevronLeft
} from 'lucide-react'
import api from '../services/api'

interface RecycleItem {
  doc_id: string
  title: string
  category: string
  deleted_at: number
  expires_at: number
  remaining_days: number
}

interface Props {
  onClose: () => void
  onRestored?: () => void
}

export default function RecycleBinPage({ onClose, onRestored }: Props) {
  const [items, setItems] = useState<RecycleItem[]>([])
  const [loading, setLoading] = useState(false)
  const [operating, setOperating] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const r = await api.get('/recycle/list')
      setItems(r.data.items || [])
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const restore = async (docId: string) => {
    if (!confirm('恢复文档将同时重建知识图谱关联，确认？')) return
    setOperating(docId)
    try {
      const r = await api.post(`/recycle/restore?doc_id=${encodeURIComponent(docId)}`)
      alert(`恢复成功：${r.data.title} | 图谱重建: 节点 ${r.data.graph_rebuilt.nodes_added} 个`)
      await load()
      onRestored?.()
    } catch (e: any) {
      alert('恢复失败: ' + (e.response?.data?.detail || e.message))
    } finally {
      setOperating(null)
    }
  }

  const hardDelete = async (docId: string, title: string) => {
    if (!confirm(`确定永久删除「${title}」？此操作不可恢复！`)) return
    setOperating(docId)
    try {
      await api.delete(`/recycle/${docId}`)
      await load()
    } catch (e: any) {
      alert('删除失败: ' + (e.response?.data?.error || e.message))
    } finally {
      setOperating(null)
    }
  }

  const cleanupExpired = async () => {
    if (!confirm('清理所有已过期（>7天）的回收站项目？')) return
    try {
      const r = await api.post('/recycle/cleanup')
      alert(`清理了 ${r.data.removed} 个过期项`)
      await load()
    } catch (e: any) {
      alert('清理失败: ' + e.message)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded-lg">
            <ChevronLeft className="h-5 w-5 text-gray-500" />
          </button>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
              <Trash2 className="h-6 w-6 text-gray-500" />
              回收站
            </h1>
            <p className="text-sm text-gray-500 mt-1">已删除的文档 7 天内可恢复，恢复后自动重建图谱关联</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={cleanupExpired}
            className="px-3 py-1.5 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200"
          >
            清理过期
          </button>
          <button
            onClick={load}
            className="p-2 text-gray-500 hover:bg-gray-100 rounded-lg"
            title="刷新"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {loading && items.length === 0 ? (
        <div className="bg-white rounded-2xl p-12 text-center text-gray-400">加载中...</div>
      ) : items.length === 0 ? (
        <div className="bg-white rounded-2xl p-12 text-center text-gray-400">
          <Trash2 className="h-12 w-12 mx-auto mb-3 text-gray-200" />
          <p>回收站是空的</p>
        </div>
      ) : (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100 text-xs text-gray-500 uppercase">
                <th className="px-4 py-3 text-left">文档</th>
                <th className="px-4 py-3 text-left">分类</th>
                <th className="px-4 py-3 text-left">删除时间</th>
                <th className="px-4 py-3 text-left">剩余天数</th>
                <th className="px-4 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {items.map((it) => (
                <tr key={it.doc_id} className="hover:bg-gray-50/80">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-gray-400" />
                      <span className="font-medium text-gray-900 text-sm">{it.title}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">{it.category}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {new Date(it.deleted_at * 1000).toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded ${
                      it.remaining_days < 1
                        ? 'bg-red-50 text-red-700'
                        : 'bg-blue-50 text-blue-700'
                    }`}>
                      <Clock className="h-3 w-3" />
                      {it.remaining_days.toFixed(1)} 天
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={() => restore(it.doc_id)}
                        disabled={operating === it.doc_id}
                        className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-blue-600 hover:bg-blue-50 rounded-lg disabled:opacity-50"
                      >
                        <RotateCcw className="h-3 w-3" />
                        恢复
                      </button>
                      <button
                        onClick={() => hardDelete(it.doc_id, it.title)}
                        disabled={operating === it.doc_id}
                        className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-red-600 hover:bg-red-50 rounded-lg disabled:opacity-50"
                      >
                        <X className="h-3 w-3" />
                        永久删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="bg-amber-50 border border-amber-100 rounded-xl p-3 flex items-start gap-2">
        <AlertTriangle className="h-4 w-4 text-amber-600 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-amber-700">
          回收站文档 7 天后自动清理；恢复时仅重建文档元数据与图谱关联，向量数据需要重新上传才能检索。
        </p>
      </div>
    </div>
  )
}
