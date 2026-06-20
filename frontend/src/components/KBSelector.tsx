/**
 * 任务 2：知识库选择器
 * - 顶部下拉：当前 KB（含"全部"选项）
 * - 弹层：创建 / 删除
 */
import { useState } from 'react'
import { ChevronDown, Plus, Trash2, Database, Globe } from 'lucide-react'
import { useKB } from '../contexts/KBContext'

export default function KBSelector() {
    const { currentKBId, setCurrentKBId, knowledgeBases, createKB, deleteKB } = useKB()
    const [open, setOpen] = useState(false)
    const [showCreate, setShowCreate] = useState(false)
    const [newName, setNewName] = useState('')
    const [newDesc, setNewDesc] = useState('')
    const [busy, setBusy] = useState(false)

    const currentKB = knowledgeBases.find((k) => k.id === currentKBId)
    const label = currentKBId === 'all'
        ? '全部知识库'
        : (currentKBId === 'default' ? '默认知识库' : (currentKB?.name || '未知'))

    const handleCreate = async () => {
        if (!newName.trim()) return
        try {
            setBusy(true)
            await createKB(newName.trim(), newDesc.trim())
            setNewName('')
            setNewDesc('')
            setShowCreate(false)
        } catch (e: any) {
            alert('创建失败: ' + (e.response?.data?.detail || e.message))
        } finally {
            setBusy(false)
        }
    }

    const handleDelete = async (id: string, name: string) => {
        if (!confirm(`确认删除知识库「${name}」?\n此操作将清除该库下所有文档、向量、图谱节点。`)) return
        try {
            setBusy(true)
            await deleteKB(id)
        } catch (e: any) {
            alert('删除失败: ' + (e.response?.data?.detail || e.message))
        } finally {
            setBusy(false)
        }
    }

    return (
        <div className="relative">
            {/* 触发按钮 */}
            <button
                onClick={() => setOpen(!open)}
                className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm bg-gradient-to-r from-blue-50 to-indigo-50 hover:from-blue-100 hover:to-indigo-100 border border-blue-100/50 transition-all"
            >
                <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-white shadow-sm">
                    {currentKBId === 'all' ? <Globe className="h-4 w-4" /> : <Database className="h-4 w-4" />}
                </div>
                <div className="flex-1 min-w-0 text-left">
                    <p className="text-[11px] font-semibold text-blue-500 uppercase tracking-wider">知识库</p>
                    <p className="font-semibold text-gray-800 truncate">{label}</p>
                </div>
                <ChevronDown className={`h-4 w-4 text-gray-500 transition-transform ${open ? 'rotate-180' : ''}`} />
            </button>

            {/* 下拉弹层 */}
            {open && (
                <>
                    <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
                    <div className="absolute left-0 right-0 mt-2 bg-white rounded-xl shadow-2xl border border-gray-100 z-50 overflow-hidden">
                        <div className="max-h-80 overflow-y-auto py-1">
                            {/* 全部选项 */}
                            <button
                                onClick={() => { setCurrentKBId('all'); setOpen(false) }}
                                className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-gray-50 ${currentKBId === 'all' ? 'bg-blue-50' : ''}`}
                            >
                                <Globe className="h-4 w-4 text-gray-500" />
                                <span className="flex-1 text-left">全部知识库</span>
                                <span className="text-[11px] text-gray-400">不限定</span>
                            </button>
                            {/* 默认库 */}
                            <button
                                onClick={() => { setCurrentKBId('default'); setOpen(false) }}
                                className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-gray-50 ${currentKBId === 'default' ? 'bg-blue-50' : ''}`}
                            >
                                <Database className="h-4 w-4 text-gray-500" />
                                <span className="flex-1 text-left">默认知识库</span>
                                <span className="text-[11px] text-gray-400">default</span>
                            </button>
                            <div className="border-t border-gray-100 my-1" />
                            <div className="px-3 py-1.5 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">
                                我的知识库
                            </div>
                            {knowledgeBases.filter(k => k.id !== 'default').map((kb) => (
                                <div key={kb.id} className={`flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-gray-50 group ${currentKBId === kb.id ? 'bg-blue-50' : ''}`}>
                                    <button
                                        onClick={() => { setCurrentKBId(kb.id); setOpen(false) }}
                                        className="flex items-center gap-3 flex-1 min-w-0 text-left"
                                    >
                                        <Database className="h-4 w-4 text-indigo-500 shrink-0" />
                                        <div className="flex-1 min-w-0">
                                            <p className="font-medium text-gray-800 truncate">{kb.name}</p>
                                            {kb.description && <p className="text-[11px] text-gray-400 truncate">{kb.description}</p>}
                                        </div>
                                    </button>
                                    <button
                                        onClick={(e) => { e.stopPropagation(); handleDelete(kb.id, kb.name) }}
                                        className="opacity-0 group-hover:opacity-100 p-1.5 hover:bg-red-50 rounded transition-all"
                                        title="删除"
                                    >
                                        <Trash2 className="h-3.5 w-3.5 text-red-500" />
                                    </button>
                                </div>
                            ))}
                            {knowledgeBases.filter(k => k.id !== 'default').length === 0 && (
                                <p className="px-4 py-3 text-xs text-gray-400 text-center">暂无自定义知识库</p>
                            )}
                        </div>
                        {/* 创建入口 */}
                        <div className="border-t border-gray-100 p-2">
                            {showCreate ? (
                                <div className="space-y-2 p-2">
                                    <input
                                        type="text"
                                        placeholder="知识库名称"
                                        value={newName}
                                        onChange={(e) => setNewName(e.target.value)}
                                        className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-200"
                                        autoFocus
                                    />
                                    <input
                                        type="text"
                                        placeholder="描述（可选）"
                                        value={newDesc}
                                        onChange={(e) => setNewDesc(e.target.value)}
                                        className="w-full px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-200"
                                    />
                                    <div className="flex gap-2">
                                        <button
                                            onClick={handleCreate}
                                            disabled={busy || !newName.trim()}
                                            className="flex-1 px-3 py-1.5 text-xs font-semibold text-white bg-blue-500 hover:bg-blue-600 rounded-lg disabled:opacity-50"
                                        >
                                            {busy ? '创建中...' : '确认创建'}
                                        </button>
                                        <button
                                            onClick={() => { setShowCreate(false); setNewName(''); setNewDesc('') }}
                                            className="px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 rounded-lg"
                                        >
                                            取消
                                        </button>
                                    </div>
                                </div>
                            ) : (
                                <button
                                    onClick={() => setShowCreate(true)}
                                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 rounded-lg"
                                >
                                    <Plus className="h-4 w-4" />
                                    <span>新建知识库</span>
                                </button>
                            )}
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}
