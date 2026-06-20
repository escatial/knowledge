/**
 * AI 问答任务全局存储
 *
 * 解决问题：用户切走页面 → 组件 unmount → SSE fetch 被取消 → 后端流式生成中断。
 *
 * 核心策略：
 * 1. 用 localStorage 持久化进行中的任务 ID（页面刷新也不丢）
 * 2. 用 React Provider 暴露给所有页面（切页不丢）
 * 3. 切到其它页面时组件 unmount 不影响 fetch；切回时从全局 store 拉取结果
 * 4. 任务完成后从 store 中移除
 *
 * v2 增强：
 * - 集成知识库分类多选（需求 7）
 * - 集成思考/答案分离字段（需求 6）
 * - 集成引用序号溯源（需求 5）
 * - 模块加载时自动恢复 pending 任务
 */
import { create } from './tinyStore'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string  // 最终答案
  /** 思考过程（v2 拆分） */
  thinking?: string
  citations?: any[]
  confidence?: number
  /** 任务 ID（assistant 消息专用；切页后通过此 ID 找回答案） */
  taskId?: string
  /** 任务状态：pending / running / done / error */
  taskStatus?: 'pending' | 'running' | 'done' | 'error'
  /** 检索时使用的知识库分类列表（v2） */
  selectedCategories?: string[]
  timestamp: number
}

interface TaskStore {
  messages: ChatMessage[]
  // 当前 session 的 ID
  sessionId: string
  // 当前选中的知识库分类（v2：斜杠触发）
  selectedCategories: string[]
}

const STORAGE_KEY = 'ai_task_store_v1'

const initial: TaskStore = {
  messages: [],
  sessionId: `session_${Date.now()}`,
  selectedCategories: [],
}

export const aiTaskStore = create<TaskStore>(initial, {
  persistKey: STORAGE_KEY,
})

// 给 store 增加几个 action
export function setSessionId(sid: string) {
  aiTaskStore.setState((prev) => ({ ...prev, sessionId: sid }))
}

export function setSelectedCategories(cats: string[]) {
  aiTaskStore.setState((prev) => ({ ...prev, selectedCategories: cats }))
}

export function toggleSelectedCategory(cat: string) {
  const cur = aiTaskStore.getState().selectedCategories
  const next = cur.includes(cat) ? cur.filter((c) => c !== cat) : [...cur, cat]
  setSelectedCategories(next)
}

export function addUserMessage(content: string, selectedCategories?: string[]): ChatMessage {
  const msg: ChatMessage = {
    id: `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    role: 'user',
    content,
    selectedCategories,
    timestamp: Date.now(),
  }
  aiTaskStore.setState((prev) => ({
    ...prev,
    messages: [...prev.messages, msg],
  }))
  return msg
}

export function addAssistantPlaceholder(taskId: string, selectedCategories?: string[]): ChatMessage {
  const msg: ChatMessage = {
    id: `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    role: 'assistant',
    content: '',
    thinking: '',
    taskId,
    taskStatus: 'running',
    selectedCategories,
    timestamp: Date.now(),
  }
  aiTaskStore.setState((prev) => ({
    ...prev,
    messages: [...prev.messages, msg],
  }))
  return msg
}

export function updateAssistant(taskId: string, patch: Partial<ChatMessage>) {
  aiTaskStore.setState((prev) => ({
    ...prev,
    messages: prev.messages.map((m) =>
      m.taskId === taskId ? { ...m, ...patch } : m
    ),
  }))
}

export function clearAll() {
  aiTaskStore.setState({
    messages: [],
    sessionId: `session_${Date.now()}`,
    selectedCategories: [],
  })
}

/**
 * 模块加载时执行：扫描所有 pending 任务，触发 AIChat 重新拉取。
 * AIChat 会在 import 时调此函数，启动轮询。
 *
 * 此处仅作为标记，让 build 优化器知道它会被使用。
 */
export function resumePendingTasks(): ChatMessage[] {
  const all = aiTaskStore.getState().messages
  return all.filter((m) => m.taskId && m.taskStatus === 'running')
}

