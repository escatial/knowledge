/**
 * 任务 P1-2 / T2：标签选择器
 *
 * - 标签云：按 doc_count 降序显示，颜色按 category 区分
 * - 支持多选/取消选择
 * - 显示选中数量 badge
 * - 用于 DocumentsPage 顶部快速过滤
 */
import { useEffect, useState, useCallback } from 'react'
import { Tag, X, Loader2, Plus } from 'lucide-react'
import api from '../services/api'

interface TagInfo {
  name: string
  display_name?: string
  category: string
  color: string
  doc_count: number
  description?: string
}

interface Props {
  selected: string[]
  onChange: (next: string[]) => void
  maxDisplay?: number
}

const CATEGORY_COLORS: Record<string, string> = {
  topic:    'bg-blue-100 text-blue-700 border-blue-200 hover:bg-blue-200',
  type:     'bg-green-100 text-green-700 border-green-200 hover:bg-green-200',
  level:    'bg-amber-100 text-amber-700 border-amber-200 hover:bg-amber-200',
  language: 'bg-purple-100 text-purple-700 border-purple-200 hover:bg-purple-200',
  custom:   'bg-gray-100 text-gray-700 border-gray-200 hover:bg-gray-200',
}

const CATEGORY_LABELS: Record<string, string> = {
  topic: '主题', type: '类型', level: '难度', language: '语言', custom: '自定义',
}

export default function TagPicker({ selected, onChange, maxDisplay = 30 }: Props) {
  const [tags, setTags] = useState<TagInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [filterCategory, setFilterCategory] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [newName, setNewName] = useState('')
  const [newCategory, setNewCategory] = useState('custom')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await api.get('/api/tags', { params: filterCategory ? { category: filterCategory } : {} })
      setTags(r.data.tags || [])
    } catch (e) {
      setTags([])
    } finally {
      setLoading(false)
    }
  }, [filterCategory])

  useEffect(() => { load() }, [load])

  const toggle = (name: string) => {
    if (selected.includes(name)) {
      onChange(selected.filter(n => n !== name))
    } else {
      onChange([...selected, name])
    }
  }

  const handleCreate = async () => {
    if (!newName.trim()) return
    try {
      await api.post('/api/tags', { name: newName, category: newCategory })
      setNewName('')
      setShowAdd(false)
      load()
    } catch (e: any) {
      alert(e?.response?.data?.detail || '创建失败')
    }
  }

  const displayTags = tags.slice(0, maxDisplay)
  const categories = ['topic', 'type', 'level', 'language', 'custom']

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4">
      {/* 标题栏 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Tag className="h-4 w-4 text-blue-600" />
          <h3 className="text-sm font-semibold text-gray-900">标签筛选</h3>
          {selected.length > 0 && (
            <span className="px-1.5 py-0.5 text-xs rounded-full bg-blue-100 text-blue-700">
              {selected.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowAdd(s => !s)}
            className="text-xs text-blue-600 hover:text-blue-700 flex items-center gap-1 px-2 py-1 rounded hover:bg-blue-50"
          >
            <Plus className="h-3 w-3" />
            新建
          </button>
          {selected.length > 0 && (
            <button
              onClick={() => onChange([])}
              className="text-xs text-gray-500 hover:text-gray-700 px-2 py-1 rounded hover:bg-gray-50"
            >
              清除
            </button>
          )}
        </div>
      </div>

      {/* 分类切换 */}
      <div className="flex gap-1 mb-3 flex-wrap">
        <button
          onClick={() => setFilterCategory(null)}
          className={`text-xs px-2 py-0.5 rounded ${
            !filterCategory ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          全部
        </button>
        {categories.map(c => (
          <button
            key={c}
            onClick={() => setFilterCategory(c)}
            className={`text-xs px-2 py-0.5 rounded ${
              filterCategory === c ? CATEGORY_COLORS[c] : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {CATEGORY_LABELS[c] || c}
          </button>
        ))}
      </div>

      {/* 新建标签表单 */}
      {showAdd && (
        <div className="mb-3 p-2 rounded-lg bg-gray-50 border border-gray-100 flex items-center gap-2">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="标签名"
            className="flex-1 px-2 py-1 text-sm rounded border border-gray-200"
          />
          <select
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value)}
            className="px-2 py-1 text-sm rounded border border-gray-200"
          >
            {categories.map(c => <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>)}
          </select>
          <button
            onClick={handleCreate}
            className="px-3 py-1 text-xs rounded bg-blue-600 text-white hover:bg-blue-700"
          >
            创建
          </button>
        </div>
      )}

      {/* 标签云 */}
      {loading ? (
        <div className="flex items-center justify-center py-4 text-gray-400">
          <Loader2 className="h-4 w-4 animate-spin" />
        </div>
      ) : displayTags.length === 0 ? (
        <div className="text-center py-4 text-xs text-gray-400">
          {filterCategory ? `${CATEGORY_LABELS[filterCategory]} 维度暂无标签` : '暂无标签，点击"新建"创建'}
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {displayTags.map(t => {
            const isSelected = selected.includes(t.name)
            return (
              <button
                key={t.name}
                onClick={() => toggle(t.name)}
                className={`group inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded-full border transition-all ${
                  isSelected
                    ? 'bg-blue-600 text-white border-blue-600 shadow-sm'
                    : CATEGORY_COLORS[t.category] || CATEGORY_COLORS.custom
                }`}
              >
                <span>{t.display_name || t.name}</span>
                {t.doc_count > 0 && (
                  <span className={`px-1 text-[10px] rounded ${
                    isSelected ? 'bg-blue-700 text-blue-100' : 'bg-white/50'
                  }`}>
                    {t.doc_count}
                  </span>
                )}
                {isSelected && <X className="h-2.5 w-2.5" />}
              </button>
            )
          })}
          {tags.length > maxDisplay && (
            <span className="text-xs text-gray-400 self-center">
              +{tags.length - maxDisplay} 更多
            </span>
          )}
        </div>
      )}
    </div>
  )
}
