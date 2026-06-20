/**
 * 任务 2：聊天流式会话保活管理器（单例）
 *
 * 解决：用户切走页面后 ChatPage unmount，回答进程会异常终止
 *
 * 设计：模块级 singleton，生命周期独立于 React 组件
 * - 提交任务：POST /ai/ask/async → 拿到 task_id
 * - 持续轮询：每 500ms GET /ai/tasks/{task_id} 拿累积 text
 * - 状态推送：notify 订阅者更新 UI
 * - 切页面：组件 unmount，manager 继续轮询
 * - 切回：组件 mount，从 manager 恢复 state
 * - localStorage 持久化：跨刷新也能恢复活跃 task
 */
import { aiApi } from './api'

// ===== 任务状态类型 =====
export interface TaskInfo {
    task_id: string
    status: 'running' | 'done' | 'error'
    text: string             // 累积回答文本
    citations?: any[]
    confidence?: number
    model?: string
    error?: string
    question: string
    session_id: string
    started_at: number
}

const STORAGE_KEY = 'chat_active_task'
const POLL_INTERVAL_MS = 500

// ===== 单例 =====
class ChatStreamManager {
    private current: TaskInfo | null = null
    private pollTimer: number | null = null
    private subscribers: Set<(t: TaskInfo | null) => void> = new Set()
    private notifiedDone = false

    /**
     * 启动一个新任务
     */
    async start(
        question: string,
        sessionId: string,
        context?: any[],
        model?: string,
        selectedCategories?: string[]
    ): Promise<{ task_id: string }> {
        // 提交前先停掉旧 task（如果有）
        this.stop(false)

        const res = await aiApi.askAsync(question, sessionId, context, model, selectedCategories)
        const taskId = res.data.task_id

        this.current = {
            task_id: taskId,
            status: 'running',
            text: '',
            question,
            session_id: sessionId,
            started_at: Date.now()
        }
        this.notifiedDone = false
        this.persist()
        this.notify()
        this.startPolling()
        return { task_id: taskId }
    }

    /**
     * 启动轮询
     */
    private startPolling() {
        if (this.pollTimer !== null) return
        this.pollTimer = window.setInterval(() => this.poll(), POLL_INTERVAL_MS)
    }

    /**
     * 停止轮询（页面级 - 不删除任务）
     * 任务 2 关键修复：默认不清理 current/localStorage
     * - HMR/页面切换/组件 unmount 不应清理任务
     * - 只有显式调用 clearAndStop() 才彻底清理
     */
    stop(notify = true) {
        console.log('[CSM.stop] called', { notify, current_id: this.current?.task_id?.slice(0, 8) })
        if (this.pollTimer !== null) {
            window.clearInterval(this.pollTimer)
            this.pollTimer = null
        }
        if (notify) {
            this.notify()
        }
    }

    /**
     * 彻底停止并清理（用户主动取消 / 错误终止时调用）
     */
    clearAndStop() {
        this.stop(false)
        this.current = null
        this.persist()
        this.notify()
    }

    /**
     * 轮询任务状态
     */
    private async poll() {
        if (!this.current) {
            this.stop(false)
            return
        }
        try {
            const res = await aiApi.getTask(this.current.task_id)
            const data = res.data
            if (!data) return

            // 合并新累积文本
            const newText = data.text || ''
            const newStatus = data.status

            // 检测文本是否有更新
            if (newText !== this.current.text || newStatus !== this.current.status) {
                this.current = {
                    ...this.current,
                    text: newText,
                    status: newStatus,
                    citations: data.citations ?? this.current.citations,
                    confidence: data.confidence ?? this.current.confidence,
                    model: data.model ?? this.current.model,
                    error: data.error ?? this.current.error
                }
                this.persist()
                this.notify()
            }

            // 完成 / 错误后停止
            if (newStatus === 'done' || newStatus === 'error') {
                if (!this.notifiedDone) {
                    this.notifiedDone = true
                    this.notify()
                }
                // 任务完成后 5 秒再停止（让 UI 有时间渲染最终状态）
                // 任务 G：同时清理 this.current + localStorage（避免切回页面时 done task 持续推送）
                window.setTimeout(() => {
                    this.stop()
                    this.current = null
                    this.persist()
                }, 5000)
            }
        } catch (e) {
            console.warn('[ChatStreamManager] poll failed:', e)
        }
    }

    /**
     * 获取当前 task
     */
    get(): TaskInfo | null {
        return this.current
    }

    /**
     * 订阅状态变化
     */
    subscribe(cb: (t: TaskInfo | null) => void): () => void {
        this.subscribers.add(cb)
        // 立即推一次当前状态
        cb(this.current)
        return () => this.subscribers.delete(cb)
    }

    private notify() {
        this.subscribers.forEach(cb => {
            try { cb(this.current) } catch (e) { console.error(e) }
        })
    }

    /**
     * 持久化到 localStorage（供跨刷新恢复）
     */
    private persist() {
        try {
            if (this.current) {
                localStorage.setItem(STORAGE_KEY, JSON.stringify(this.current))
            } else {
                localStorage.removeItem(STORAGE_KEY)
            }
            console.log('[CSM.persist]', this.current ? `set ${this.current.task_id.slice(0,8)}` : 'clear')
        } catch (e) {
            console.warn('[ChatStreamManager] persist failed:', e)
        }
    }

    /**
     * 从 localStorage 恢复（应用启动时调用）
     */
    restore() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY)
            if (!raw) return
            const task = JSON.parse(raw) as TaskInfo
            // 仅恢复未超时的 running 任务（10 分钟内）
            if (task.status === 'running' && Date.now() - task.started_at < 600_000) {
                this.current = task
                this.startPolling()
                this.notify()
            } else {
                // 旧的已完成/超时的 task，清掉
                localStorage.removeItem(STORAGE_KEY)
            }
        } catch (e) {
            console.warn('[ChatStreamManager] restore failed:', e)
        }
    }
}

// 全局单例（任务 2 关键修复：用 globalThis 抗 HMR）
// Vite HMR 会重新执行模块，导致模块级 `new` 失效
// 改用 globalThis 保存，让 HMR 后实例仍然唯一
const globalRef = globalThis as any
if (!globalRef.__chatStreamManager) {
    globalRef.__chatStreamManager = new ChatStreamManager()
    // 仅在首次创建时执行 restore
    if (typeof window !== 'undefined') {
        globalRef.__chatStreamManager.restore()
    }
}
export const chatStreamManager: ChatStreamManager = globalRef.__chatStreamManager
