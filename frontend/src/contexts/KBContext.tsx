/**
 * 任务 2：知识库 Context（全局联动）
 *
 * - 维护当前选中的 knowledge_base_id
 * - 持久化到 localStorage
 * - 提供切换、列表、创建、删除、迁移能力
 */
import { createContext, useContext, useEffect, useState, useCallback, ReactNode } from 'react'
import { knowledgeBaseApi } from '../services/api'

export interface KnowledgeBase {
    id: string
    name: string
    description?: string
    created_at?: string
    doc_count?: number
}

interface KBContextValue {
    currentKBId: string
    setCurrentKBId: (id: string) => void
    knowledgeBases: KnowledgeBase[]
    refreshKBs: () => Promise<void>
    createKB: (name: string, description?: string) => Promise<KnowledgeBase>
    deleteKB: (id: string) => Promise<void>
}

const KBContext = createContext<KBContextValue | null>(null)

export const useKB = (): KBContextValue => {
    const ctx = useContext(KBContext)
    if (!ctx) {
        throw new Error('useKB must be used within KBProvider')
    }
    return ctx
}

export const KBProvider = ({ children }: { children: ReactNode }) => {
    const [currentKBId, setCurrentKBIdState] = useState<string>(() => {
        try {
            return localStorage.getItem('current_kb_id') || 'all'
        } catch {
            return 'all'
        }
    })
    const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([])

    const setCurrentKBId = useCallback((id: string) => {
        setCurrentKBIdState(id)
        try {
            localStorage.setItem('current_kb_id', id)
        } catch {
            // ignore
        }
        // 触发全局事件，通知列表/图谱/搜索/问答页刷新
        window.dispatchEvent(new CustomEvent('kb-changed', { detail: { kbId: id } }))
    }, [])

    const refreshKBs = useCallback(async () => {
        try {
            const list = await knowledgeBaseApi.list()
            setKnowledgeBases(list || [])
        } catch (e) {
            console.error('[KB] 加载知识库列表失败:', e)
        }
    }, [])

    const createKB = useCallback(async (name: string, description = ''): Promise<KnowledgeBase> => {
        const kb = await knowledgeBaseApi.create(name, description)
        await refreshKBs()
        return kb
    }, [refreshKBs])

    const deleteKB = useCallback(async (id: string) => {
        await knowledgeBaseApi.delete(id)
        if (currentKBId === id) {
            setCurrentKBId('all')
        }
        await refreshKBs()
    }, [currentKBId, refreshKBs, setCurrentKBId])

    useEffect(() => {
        refreshKBs()
    }, [refreshKBs])

    return (
        <KBContext.Provider value={{ currentKBId, setCurrentKBId, knowledgeBases, refreshKBs, createKB, deleteKB }}>
            {children}
        </KBContext.Provider>
    )
}
