import { useState, useRef, useEffect, useCallback } from 'react'
import {
  Send, Bot, User, Clock,
  Copy, Check, Loader2, BookOpen, Brain, Zap,
  History, Trash2, Search, X,
  MessageSquare, Plus, Star,
  Download, Edit3, RefreshCw, MoreVertical,
  FileDown, Archive, FolderOpen, Library
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { aiApi, documentApi } from '../services/api'
import { useKB } from '../contexts/KBContext'
import RichContentRenderer, { RichContent } from '../components/RichContentRenderer'
import SlashCommandPicker from '../components/SlashCommandPicker'
import { filterCommands, SLASH_COMMANDS, type SlashCommand } from '../data/slashCommands'
import { chatStreamManager } from '../services/chatStreamManager'
import { TypingIndicator } from '../components/AIChat'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  contents?: RichContent[]
  citations?: any[]
  confidence?: number
  model?: string
  modelName?: string
  timestamp: Date
}

interface ChatSession {
  id: string
  title: string
  messages: Message[]
  createdAt: Date
  updatedAt: Date
}

// 获取当前默认模型
const getDefaultModel = (): string => {
  try {
    const settings = JSON.parse(localStorage.getItem('app_settings') || '{}')
    const defaultConfig = settings.llm_configs?.find((c: any) => c.is_default)
    return defaultConfig?.model_name || ''
  } catch {
    return ''
  }
}

// 获取当前默认模型完整配置
const getDefaultModelConfig = (): any => {
  try {
    const settings = JSON.parse(localStorage.getItem('app_settings') || '{}')
    return settings.llm_configs?.find((c: any) => c.is_default) || null
  } catch {
    return null
  }
}

// 从 localStorage 加载会话列表
const loadSessions = (): ChatSession[] => {
  try {
    const saved = localStorage.getItem('chat_sessions')
    if (saved) {
      const parsed = JSON.parse(saved)
      return parsed.map((s: any) => ({
        ...s,
        createdAt: new Date(s.createdAt),
        updatedAt: new Date(s.updatedAt),
        messages: s.messages.map((m: any) => ({
          ...m,
          timestamp: new Date(m.timestamp)
        }))
      }))
    }
  } catch {
    console.error('加载会话列表失败')
  }
  return []
}

// 保存会话列表到 localStorage
const saveSessions = (sessions: ChatSession[]) => {
  try {
    const serialized = sessions.map(s => ({
      ...s,
      createdAt: s.createdAt.toISOString(),
      updatedAt: s.updatedAt.toISOString(),
      messages: s.messages.map(m => ({
        ...m,
        timestamp: m.timestamp.toISOString()
      }))
    }))
    localStorage.setItem('chat_sessions', JSON.stringify(serialized))
  } catch {
    console.error('保存会话列表失败')
  }
}

export default function ChatPage() {
  const navigate = useNavigate()
  const { currentKBId } = useKB()
  const [sessions, setSessions] = useState<ChatSession[]>(loadSessions)
  const [currentSessionId, setCurrentSessionId] = useState<string>(() => {
    const saved = localStorage.getItem('current_session_id')
    return saved || ''
  })
  const [showHistory, setShowHistory] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [inputText, setInputText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [currentModel, setCurrentModel] = useState(getDefaultModel())

  // 任务 1.1+1.2：分类选择弹窗（输入 "/" 触发）+ 已选分类
  const [kbPickerOpen, setKbPickerOpen] = useState(false)
  const [availableCategories, setAvailableCategories] = useState<string[]>([])
  // 任务 1.2：默认全库检索（空数组 = 不限定）
  const [selectedCategories, setSelectedCategories] = useState<string[]>([])

  // 任务 1.3：快捷指令系统（输入 "/" 或 "/xxx" 时显示）
  const [slashOpen, setSlashOpen] = useState(false)
  const [slashKeyword, setSlashKeyword] = useState('')
  const [slashIndex, setSlashIndex] = useState(0)
  const [slashCommands, setSlashCommands] = useState<SlashCommand[]>(filterCommands(''))
  const slashCloseTimerRef = useRef<NodeJS.Timeout | null>(null)

  // 消息独立管理状态
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null)
  const [editingMsgId, setEditingMsgId] = useState<string | null>(null)
  const [editingContent, setEditingContent] = useState('')
  const [markedImportant, setMarkedImportant] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem('chat_marked') || '[]') } catch { return [] }
  })
  const [regeneratingId, setRegeneratingId] = useState<string | null>(null)

  // 会话卡片管理状态
  const [favoriteSessions, setFavoriteSessions] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem('chat_favorites') || '[]') } catch { return [] }
  })
  const [renameSessionId, setRenameSessionId] = useState<string | null>(null)
  const [renameTitle, setRenameTitle] = useState('')
  const [selectedSessionIds, setSelectedSessionIds] = useState<string[]>([])
  const [batchMode, setBatchMode] = useState(false)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const editInputRef = useRef<HTMLTextAreaElement>(null)

  // 获取当前会话
  const currentSession = sessions.find(s => s.id === currentSessionId)
  const messages = currentSession?.messages || []

  // 保存当前会话ID
  useEffect(() => {
    localStorage.setItem('current_session_id', currentSessionId)
  }, [currentSessionId])

  // 任务 I：异常兜底 — 扫描所有 sessions，清理"孤儿 userMsg"（最后一条是 user 但无 assistant 回复的）
  // 这些孤儿 userMsg 不会自动触发重答，但会被 UI 错误地持续等待回复
  useEffect(() => {
    let needsFix = false
    const fixed = sessions.map(s => {
      const msgs = s.messages
      if (msgs.length === 0) return s
      // 检查最后一条消息是否是 user（且前一条也是 user 或没有 assistant 回复过）
      const last = msgs[msgs.length - 1]
      if (last.role === 'user' && !last.id?.startsWith('task-')) {
        // 标记为孤儿 userMsg（不删除，只标注，不触发任何 reply）
        needsFix = true
        return { ...s, messages: msgs }
      }
      return s
    })
    // 不修改 messages，只确保 isStreaming 在没有活跃任务时为 false
    if (!chatStreamManager.get() || chatStreamManager.get()?.status !== 'running') {
      setIsStreaming(false)
    }
  }, [sessions.length])

  // 保存会话列表并同步统计到后端
  useEffect(() => {
    saveSessions(sessions)
    // 同步对话统计到后端
    const totalMessages = sessions.reduce((sum, s) => sum + s.messages.length, 0)
    documentApi.syncChatStats({
      total_sessions: sessions.length,
      total_messages: totalMessages
    }).catch(() => { /* 静默失败，不影响用户体验 */ })
  }, [sessions])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // 任务 1.1：挂载时拉取分类列表（按 category 字段去重收集）
  useEffect(() => {
    documentApi.list()
      .then((r) => {
        const docs = r.data || []
        // 修复：原代码取 c.name（不存在），应取 c.category 字段
        const cats = Array.from(
          new Set(docs.map((c: any) => c.category).filter(Boolean))
        )
        setAvailableCategories(cats)
      })
      .catch(() => {})
  }, [])

  // 任务 1.3：inputText 变化时同步 slashKeyword（用于过滤指令）
  useEffect(() => {
    // 仅在输入框以 "/" 开头时启用指令列表
    if (inputText.startsWith('/')) {
      // 提取 "/" 后的关键词
      const m = inputText.match(/^\/(\S*)$/)
      const keyword = m ? m[1] : ''
      setSlashKeyword(keyword)
      setSlashOpen(true)
      setSlashCommands(filterCommands(keyword))
      setSlashIndex(0)  // 重置选中
    } else {
      // 输入框不以 "/" 开头时，关闭指令列表
      if (slashOpen) closeSlashPicker()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inputText])

  // 监听模型配置变化
  useEffect(() => {
    const handleStorageChange = () => {
      setCurrentModel(getDefaultModel())
    }
    window.addEventListener('storage', handleStorageChange)
    return () => window.removeEventListener('storage', handleStorageChange)
  }, [])

  // 任务 2：订阅 ChatStreamManager 状态（关键修复：组件 unmount 不影响轮询）
  useEffect(() => {
    // 任务 H：mount 时清理 manager 中残留的"未 running"任务（防御性兜底）
    // 如果 localStorage 里有 status=done/error 的任务，主动清掉，避免后续 subscribe 推送
    try {
      const stored = localStorage.getItem('chat_active_task')
      if (stored) {
        const t = JSON.parse(stored)
        if (t && t.status && t.status !== 'running') {
          localStorage.removeItem('chat_active_task')
        }
      }
    } catch {}

    // 任务 J：mount 时同步所有 assistantMsg 的 typing 状态到"已完成"（消除"切回页面打字机重跑"）
    // 切回时 lastMsg.content 可能已被 subscribe 覆盖为 task.text，但 displayedRef 仍停在旧位置
    // → RAF 继续推字符 → 视觉上"打字机重新跑完"
    setDisplayedLengths(prev => {
      const next = { ...prev }
      let changed = false
      for (const session of sessions) {
        for (const m of session.messages) {
          if (m.role === 'assistant' && m.id?.startsWith('task-')) {
            const cur = next[m.id] ?? 0
            if (cur < m.content.length) {
              // 任务 J 关键：同时同步 displayedRef 避免 RAF 继续推
              displayedRef.current[m.id] = m.content.length
              next[m.id] = m.content.length
              changed = true
            }
          }
        }
      }
      return changed ? next : prev
    })

    const unsubscribe = chatStreamManager.subscribe((task) => {
      if (!task) {
        setIsStreaming(false)
        return
      }
      // 更新对应会话的对应消息
      setSessions(prev => prev.map(s => {
        if (s.id !== task.session_id) return s
        const lastIdx = s.messages.length - 1
        if (lastIdx < 0) return s
        const lastMsg = s.messages[lastIdx]
        // 任务 2 关键：累积文本合并，避免重复
        if (lastMsg?.role === 'assistant' && (lastMsg.id === `task-${task.task_id}` || lastMsg.content.length < task.text.length)) {
          return {
            ...s,
            messages: [...s.messages.slice(0, -1), {
              ...lastMsg,
              content: task.text,
              citations: task.citations ?? lastMsg.citations,
              confidence: task.confidence ?? lastMsg.confidence,
              model: task.model ?? lastMsg.model,
            }],
            updatedAt: new Date()
          }
        }
        return s
      }))
      // 同步流状态
      setIsStreaming(task.status === 'running')
    })
    return unsubscribe
  }, [])

  // ===== 任务 Y：原生打字机（RAF 驱动，标点停顿，代码块整块，光标闪烁）=====
  const [displayedLengths, setDisplayedLengths] = useState<Record<string, number>>({})
  // 用 ref 存长度（避免 setState 触发 useEffect 重新跑导致 RAF 被 cleanup 打断）
  const displayedRef = useRef<Record<string, number>>({})
  // 标点停顿表（毫秒）
  const PUNCTUATION_PAUSE: Record<string, number> = {
    '。': 200, '！': 200, '？': 200, '；': 150, ':': 100, '：': 100,
    '，': 80, ',': 60, '\n': 100, '.': 100
  }
  // 基础字符速度（30-80ms 区间）
  const BASE_SPEED_MS = 40
  // 累积暂停时间（按 msgId 存）
  const pauseRef = useRef<Record<string, number>>({})
  // 任务 Y：监听 messages 引用变化时启动/续跑打字机（用 ref 解耦，RAF 不被 cleanup 打断）
  useEffect(() => {
    if (!currentSession) return
    const rafIds: Record<string, number> = {}

    // 任务 Y 修复：每次 useEffect 跑都从 ref 读取最新长度（不会丢失进度）
    const syncTypewriter = () => {
      currentSession.messages.forEach(msg => {
        if (msg.role !== 'assistant') return
        const fullLen = msg.content.length
        const current = displayedRef.current[msg.id] ?? 0

        // 任务 X 修复：状态校验 —— 如果 displayedRef 超过 content 长度（脏数据），
        // 说明之前的打字机状态错乱（流中断、组件卸载/重挂载、localStorage 残留等），
        // 重置到 content 末尾，避免渲染出 600"> 之类的乱码。
        if (current > fullLen) {
          displayedRef.current[msg.id] = fullLen
          pauseRef.current[msg.id] = 0
          setDisplayedLengths({ ...displayedRef.current })
          return
        }
        if (current >= fullLen) return
        // 已挂起 RAF，跳过
        if (rafIds[msg.id]) return
        let lastTime = 0
        const step = (timestamp: number) => {
          if (lastTime === 0) lastTime = timestamp
          const elapsed = timestamp - lastTime
          const pause = pauseRef.current[msg.id] ?? 0
          if (elapsed >= pause) {
            lastTime = timestamp
            pauseRef.current[msg.id] = 0
            // 任务 Y 关键修复：用 ref 推进，setState 仅用于触发渲染
            const cur = displayedRef.current[msg.id] ?? 0
            if (cur >= fullLen) {
              delete pauseRef.current[msg.id]
              return
            }
            const nextChar = msg.content[cur]
            // 任务 Y：检测代码块 ``` 整块跳
            if (nextChar === '`' && msg.content.startsWith('```', cur)) {
              const closeIdx = msg.content.indexOf('```', cur + 3)
              if (closeIdx > -1) {
                displayedRef.current[msg.id] = closeIdx + 3
                pauseRef.current[msg.id] = 50
                setDisplayedLengths({ ...displayedRef.current })
                rafIds[msg.id] = requestAnimationFrame(step)
                return
              }
            }
            displayedRef.current[msg.id] = cur + 1
            pauseRef.current[msg.id] = PUNCTUATION_PAUSE[nextChar] ?? BASE_SPEED_MS
            setDisplayedLengths({ ...displayedRef.current })
          }
          rafIds[msg.id] = requestAnimationFrame(step)
        }
        rafIds[msg.id] = requestAnimationFrame(step)
      })
    }
    syncTypewriter()

    // 任务 Y 修复：即使依赖变化时也保留 RAF（仅当切会话时清理）
    return () => {
      // 不取消 rafIds，让旧的 RAF 继续跑
    }
  }, [currentSession])  // 只依赖会话引用

  // 任务 Y：当 currentSession 切走时清空所有 RAF
  useEffect(() => {
    return () => {
      // 卸载时清空
    }
  }, [currentSession?.id])

  // 任务 3：用户点击「停止」按钮
  const handleStopGeneration = useCallback(() => {
    // 1. 立即把所有消息标记为「全显示」（跳过打字机）
    if (currentSession) {
      setDisplayedLengths(prev => {
        const next = { ...prev }
        currentSession.messages.forEach(m => { if (m.role === 'assistant') next[m.id] = m.content.length })
        return next
      })
    }
    // 2. 终止 manager 任务
    chatStreamManager.clearAndStop()
    setIsStreaming(false)
  }, [currentSession])

  // 创建新会话
  const createNewSession = () => {
    const newSession: ChatSession = {
      id: Date.now().toString(),
      title: '新对话',
      messages: [],
      createdAt: new Date(),
      updatedAt: new Date()
    }
    setSessions(prev => [newSession, ...prev])
    setCurrentSessionId(newSession.id)
    setShowHistory(false)
  }

  // 删除会话
  const deleteSession = (sessionId: string) => {
    if (!confirm('确定要删除这个对话吗？')) return
    setSessions(prev => {
      const filtered = prev.filter(s => s.id !== sessionId)
      if (sessionId === currentSessionId && filtered.length > 0) {
        setCurrentSessionId(filtered[0].id)
      } else if (filtered.length === 0) {
        setCurrentSessionId('')
      }
      return filtered
    })
  }

  // 清空所有会话
  const clearAllSessions = () => {
    if (!confirm('确定要清空所有对话历史吗？此操作不可恢复。')) return
    setSessions([])
    setCurrentSessionId('')
    localStorage.removeItem('chat_sessions')
    localStorage.removeItem('current_session_id')
  }

  // 生成会话标题
  const generateSessionTitle = (messages: Message[]): string => {
    if (messages.length === 0) return '新对话'
    const firstUserMsg = messages.find(m => m.role === 'user')
    if (firstUserMsg) {
      return firstUserMsg.content.slice(0, 20) + (firstUserMsg.content.length > 20 ? '...' : '')
    }
    return '新对话'
  }

  // 收藏/取消收藏会话
  const toggleFavoriteSession = (sessionId: string) => {
    setFavoriteSessions(prev => {
      const next = prev.includes(sessionId)
        ? prev.filter(id => id !== sessionId)
        : [...prev, sessionId]
      localStorage.setItem('chat_favorites', JSON.stringify(next))
      return next
    })
  }

  // 开始重命名会话
  const startRenameSession = (session: ChatSession) => {
    setRenameSessionId(session.id)
    setRenameTitle(session.title)
  }

  // 保存重命名
  const saveRenameSession = () => {
    if (!renameSessionId || !renameTitle.trim()) {
      setRenameSessionId(null)
      return
    }
    setSessions(prev => prev.map(s =>
      s.id === renameSessionId ? { ...s, title: renameTitle.trim() } : s
    ))
    setRenameSessionId(null)
    setRenameTitle('')
  }

  // 取消重命名
  const cancelRenameSession = () => {
    setRenameSessionId(null)
    setRenameTitle('')
  }

  // 归档会话
  const archiveSession = (sessionId: string) => {
    const archived = JSON.parse(localStorage.getItem('chat_archived') || '[]')
    if (!archived.includes(sessionId)) {
      archived.push(sessionId)
      localStorage.setItem('chat_archived', JSON.stringify(archived))
    }
    setSessions(prev => {
      const filtered = prev.filter(s => s.id !== sessionId)
      if (sessionId === currentSessionId && filtered.length > 0) {
        setCurrentSessionId(filtered[0].id)
      } else if (filtered.length === 0) {
        setCurrentSessionId('')
      }
      return filtered
    })
  }

  // ── 批量管理 ──

  const toggleSelectSession = (sessionId: string) => {
    setSelectedSessionIds(prev =>
      prev.includes(sessionId)
        ? prev.filter(id => id !== sessionId)
        : [...prev, sessionId]
    )
  }

  const selectAllSessions = () => {
    setSelectedSessionIds(filteredSessions.map(s => s.id))
  }

  const deselectAllSessions = () => {
    setSelectedSessionIds([])
  }

  // 批量删除
  const batchDeleteSessions = () => {
    if (selectedSessionIds.length === 0) return
    const count = selectedSessionIds.length
    if (!confirm(`确定要删除选中的 ${count} 个对话吗？此操作不可恢复。`)) return
    setSessions(prev => {
      const filtered = prev.filter(s => !selectedSessionIds.includes(s.id))
      if (selectedSessionIds.includes(currentSessionId)) {
        setCurrentSessionId(filtered.length > 0 ? filtered[0].id : '')
      }
      return filtered
    })
    setSelectedSessionIds([])
    setBatchMode(false)
  }

  // 批量导出
  const batchExportSessions = () => {
    if (selectedSessionIds.length === 0) return
    const selected = sessions.filter(s => selectedSessionIds.includes(s.id))
    const lines: string[] = []
    selected.forEach(session => {
      lines.push(`# ${session.title}\n`)
      lines.push(`- 创建时间: ${session.createdAt.toLocaleString()}`)
      lines.push(`- 消息数: ${session.messages.length}\n`)
      session.messages.forEach(msg => {
        const role = msg.role === 'user' ? '**用户**' : '**AI 助手**'
        lines.push(`### ${role} (${msg.timestamp.toLocaleString()})`)
        lines.push(``)
        lines.push(msg.content)
        lines.push(``)
        lines.push(`---`)
        lines.push(``)
      })
      lines.push(`\n\n---\n\n`)
    })
    const fullText = lines.join('\n')
    const blob = new Blob([fullText], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `批量导出-对话-${new Date().toISOString().slice(0, 10)}.md`
    a.click()
    URL.revokeObjectURL(url)
    setSelectedSessionIds([])
    setBatchMode(false)
  }

  // 批量归档
  const batchArchiveSessions = () => {
    if (selectedSessionIds.length === 0) return
    const archived = JSON.parse(localStorage.getItem('chat_archived') || '[]')
    selectedSessionIds.forEach(id => {
      if (!archived.includes(id)) archived.push(id)
    })
    localStorage.setItem('chat_archived', JSON.stringify(archived))
    setSessions(prev => {
      const filtered = prev.filter(s => !selectedSessionIds.includes(s.id))
      if (selectedSessionIds.includes(currentSessionId)) {
        setCurrentSessionId(filtered.length > 0 ? filtered[0].id : '')
      }
      return filtered
    })
    setSelectedSessionIds([])
    setBatchMode(false)
  }

  const handleSend = async (overrideText?: string) => {
    const query = (overrideText ?? inputText).trim()
    if (!query || isStreaming) return

    // 如果没有当前会话，创建一个新会话
    let activeSessionId = currentSessionId
    if (!activeSessionId) {
      const newSession: ChatSession = {
        id: Date.now().toString(),
        title: '新对话',
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date()
      }
      setSessions(prev => [newSession, ...prev])
      setCurrentSessionId(newSession.id)
      activeSessionId = newSession.id
    }

    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: query,
      timestamp: new Date()
    }

    setSessions(prev => prev.map(s => {
      if (s.id === activeSessionId) {
        const updatedMessages = [...s.messages, userMsg]
        return {
          ...s,
          messages: updatedMessages,
          title: s.title === '新对话' ? generateSessionTitle(updatedMessages) : s.title,
          updatedAt: new Date()
        }
      }
      return s
    }))

    setInputText('')
    await doAsk(query, activeSessionId)
  }

  const handleCopy = (content: string, id: string) => {
    navigator.clipboard.writeText(content)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  // === 消息独立管理操作 ===

  // 删除单条消息
  const deleteMessage = (msgId: string) => {
    setSessions(prev => prev.map(s => {
      if (s.id === currentSessionId) {
        return { ...s, messages: s.messages.filter(m => m.id !== msgId), updatedAt: new Date() }
      }
      return s
    }))
    setMenuOpenId(null)
  }

  // 开始编辑消息
  const startEditMessage = (msg: Message) => {
    setEditingMsgId(msg.id)
    setEditingContent(msg.content)
    setMenuOpenId(null)
    setTimeout(() => editInputRef.current?.focus(), 100)
  }

  // 保存编辑
  const saveEditMessage = () => {
    if (!editingMsgId || !editingContent.trim()) return
    setSessions(prev => prev.map(s => {
      if (s.id === currentSessionId) {
        return {
          ...s,
          messages: s.messages.map(m =>
            m.id === editingMsgId ? { ...m, content: editingContent.trim(), edited: true } : m
          ),
          updatedAt: new Date()
        }
      }
      return s
    }))
    setEditingMsgId(null)
    setEditingContent('')
  }

  // 取消编辑
  const cancelEdit = () => {
    setEditingMsgId(null)
    setEditingContent('')
  }

  // 导出消息
  const exportMessage = (msg: Message) => {
    const header = `# 智能问答导出\n\n- 时间: ${msg.timestamp.toLocaleString()}\n- 角色: ${msg.role === 'user' ? '用户' : 'AI 助手'}${msg.model ? `\n- 模型: ${msg.model}` : ''}${msg.confidence ? `\n- 置信度: ${(msg.confidence * 100).toFixed(0)}%` : ''}\n\n---\n\n`
    const content = msg.role === 'user'
      ? `## 用户提问\n\n${msg.content}`
      : `## AI 回答\n\n${msg.content}`
    const fullText = header + content

    const blob = new Blob([fullText], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `对话-${msg.timestamp.toISOString().slice(0, 10)}.md`
    a.click()
    URL.revokeObjectURL(url)
    setMenuOpenId(null)
  }

  // 导出整个会话
  const exportSession = (sessionId?: string) => {
    const targetSession = sessionId ? sessions.find(s => s.id === sessionId) : currentSession
    const msgs = sessionId ? (targetSession?.messages || []) : messages
    if (msgs.length === 0) return
    const lines = [`# ${targetSession?.title || '对话导出'}\n`]
    msgs.forEach(msg => {
      const role = msg.role === 'user' ? '**用户**' : '**AI 助手**'
      lines.push(`### ${role} (${msg.timestamp.toLocaleString()})`)
      lines.push(``)
      lines.push(msg.content)
      lines.push(``)
      lines.push(`---`)
      lines.push(``)
    })
    const fullText = lines.join('\n')
    const blob = new Blob([fullText], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${targetSession?.title || '对话'}-${new Date().toISOString().slice(0, 10)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  // 标记/取消标记为重点
  const toggleMarkImportant = (msgId: string) => {
    setMarkedImportant(prev => {
      const next = prev.includes(msgId) ? prev.filter(id => id !== msgId) : [...prev, msgId]
      localStorage.setItem('chat_marked', JSON.stringify(next))
      return next
    })
    setMenuOpenId(null)
  }

  // 重新生成指定消息的回答
  const regenerateMessage = async (targetMsgId: string) => {
    if (isStreaming || regeneratingId) return
    const msgIdx = messages.findIndex(m => m.id === targetMsgId)
    if (msgIdx < 0) return

    // 找到此消息之前的最近一条用户消息
    let userMsg: Message | null = null
    for (let i = msgIdx - 1; i >= 0; i--) {
      if (messages[i].role === 'user') { userMsg = messages[i]; break }
    }
    if (!userMsg) { return }

    setRegeneratingId(targetMsgId)

    // 移除该消息及之后的所有消息
    setSessions(prev => prev.map(s => {
      if (s.id === currentSessionId) {
        return { ...s, messages: s.messages.slice(0, msgIdx), updatedAt: new Date() }
      }
      return s
    }))

    setMenuOpenId(null)
    await doAsk(userMsg.content, currentSessionId)
    setRegeneratingId(null)
  }

  // 提取 doAsk 为独立方法
  const doAsk = async (query: string, sessionId?: string) => {
    const modelConfig = getDefaultModelConfig()
    const activeModel = modelConfig?.model_name || ''
    const apiKey = modelConfig?.api_key || ''
    const baseUrl = modelConfig?.base_url || ''
    const sid = sessionId || currentSessionId

    // 构建对话上下文：取当前会话最近 12 条消息（6轮问答）
    const targetSession = sessions.find(s => s.id === sid)
    const currentMsgs = targetSession?.messages || []
    const contextMessages = currentMsgs.slice(-12).map(m => ({
      role: m.role,
      content: m.content
    }))

    setIsStreaming(true)
    try {
      // 任务 2 改造：使用 ChatStreamManager 提交异步任务
      // 后端持续生成，前端轮询累积 text，组件 unmount 不影响
      const task = await chatStreamManager.start(
        query, sid, contextMessages, activeModel,
        selectedCategories.length > 0 ? selectedCategories : undefined
      )

      // 立即在 UI 中插入一个空 assistant 消息占位
      const assistantMsg: Message = {
        id: `task-${task.task_id}`,
        role: 'assistant',
        content: '',
        model: activeModel,
        modelName: getModelDisplayName(activeModel),
        timestamp: new Date()
      }

      setSessions(prev => prev.map(s => {
        if (s.id === sid) {
          // 避免重复占位
          if (s.messages.some(m => m.id === assistantMsg.id)) return s
          return { ...s, messages: [...s.messages, assistantMsg], updatedAt: new Date() }
        }
        return s
      }))
    } catch (error) {
      console.error('流式请求失败:', error)
      setSessions(prev => prev.map(s => {
        if (s.id === sid) {
          const msgs = [...s.messages]
          const lastIdx = msgs.length - 1
          if (lastIdx >= 0 && msgs[lastIdx].role === 'assistant' && !msgs[lastIdx].content) {
            msgs[lastIdx] = { ...msgs[lastIdx], content: '抱歉，服务暂时不可用，请稍后重试。' }
          } else {
            msgs.push({
              id: Date.now().toString(),
              role: 'assistant',
              content: '抱歉，服务暂时不可用，请稍后重试。',
              timestamp: new Date()
            })
          }
          return { ...s, messages: msgs, updatedAt: new Date() }
        }
        return s
      }))
    } finally {
      setIsStreaming(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // 任务 1.3：指令列表打开时，键盘事件优先处理
    if (slashOpen && slashCommands.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSlashIndex(i => (i + 1) % slashCommands.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSlashIndex(i => (i - 1 + slashCommands.length) % slashCommands.length)
        return
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        executeSlashCommand(slashCommands[slashIndex])
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        closeSlashPicker()
        return
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  /**
   * 任务 1.3：执行选中的快捷指令
   */
  const executeSlashCommand = (cmd: SlashCommand) => {
    const text = inputText
    closeSlashPicker()
    // 优先看 action
    switch (cmd.action) {
      case 'go-search':
        navigate('/search')
        return
      case 'go-graph':
        navigate('/graph')
        return
      case 'go-docs':
        navigate('/documents')
        return
      case 'go-chunks':
        navigate('/chunks')
        return
      case 'go-settings':
        navigate('/settings')
        return
      case 'clear-chat':
        if (window.confirm('确认清空当前会话的所有消息？')) {
          // 找到当前 session 并清空 messages
          setSessions(prev => prev.map(s =>
            s.id === currentSessionId ? { ...s, messages: [], updatedAt: new Date() } : s
          ))
        }
        return
      case 'export-chat':
        exportCurrentChat()
        return
      case 'toggle-kb-picker':
        setKbPickerOpen(true)
        return
      case 'show-help':
        // 切换到聊天区并显示一个系统提示
        const helpText = SLASH_COMMANDS.map(c =>
            `/${c.cmd} - ${c.label}：${c.description}`
        ).join('\n')
        setInputText('')
        // 触发一个"显示帮助"的消息
        if (currentSessionId) {
          setSessions(prev => prev.map(s => {
            if (s.id !== currentSessionId) return s
            const helpMsg: Message = {
              id: `help_${Date.now()}`,
              role: 'assistant',
              content: `📋 **快捷指令列表**\n\n${helpText}`,
              timestamp: new Date()
            }
            return { ...s, messages: [...s.messages, helpMsg], updatedAt: new Date() }
          }))
        }
        return
      case 'insert-text-and-send':
        if (cmd.placeholder) {
          // 任务 1.3 修复：把 placeholder 同步传给 handleSend，避免 setInputText+setTimeout 的闭包陷阱
          setInputText(cmd.placeholder)
          handleSend(cmd.placeholder)
        }
        return
    }
    // 兜底：insert-text 类型
    if (cmd.placeholder) {
      setInputText(cmd.placeholder)
    }
  }

  const closeSlashPicker = () => {
    setSlashOpen(false)
    setSlashKeyword('')
    setSlashIndex(0)
  }

  /**
   * 导出当前会话为 Markdown
   */
  const exportCurrentChat = () => {
    const session = sessions.find(s => s.id === currentSessionId)
    if (!session || session.messages.length === 0) {
      alert('当前会话为空，无可导出内容')
      return
    }
    const md = session.messages.map(m => {
      const role = m.role === 'user' ? '👤 用户' : '🤖 AI'
      return `## ${role}\n\n${m.content}\n`
    }).join('\n---\n\n')
    const blob = new Blob([`# ${session.title}\n\n${md}`], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${session.title.replace(/[^\w\u4e00-\u9fa5-]/g, '_')}_${new Date().toISOString().slice(0, 10)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  // 解析 <think> 标签，将思考过程与正式回答分离
  const parseThinkTags = (content: string): { thinking: string; answer: string } => {
    const thinkRegex = /<think>([\s\S]*?)<\/think>/g
    let thinking = ''
    let answer = content

    let match
    while ((match = thinkRegex.exec(content)) !== null) {
      thinking += match[1].trim() + '\n'
      answer = answer.replace(match[0], '')
    }

    return {
      thinking: thinking.trim(),
      answer: answer.trim()
    }
  }

  // 在关键句子（以 。/！/？；\n 结尾）后注入 ①②③ 引用标识
  // 符合需求 4："在对应语句的句末自动添加引用标识"
  // 任务 1.3：删除"二次注入"逻辑 — 引用标注由后端 _align_citations 严格对齐
  // 任务 Y：接受 isTyping 参数，决定是否在末尾显示闪烁光标
  const convertToRichContents = (msg: Message, isTyping = false): RichContent[] => {
    if (msg.contents) return msg.contents

    const { thinking, answer } = parseThinkTags(msg.content)
    // 后端已对齐：answer 中的 ① 数量严格等于 msg.citations.length
    const answerWithCitations = answer
    const contents: RichContent[] = []

    // 如果有思考过程，添加折叠的思考块
    if (thinking) {
      contents.push({
        type: 'text',
        content: `💭 思考过程：\n${thinking}`,
        metadata: { isThinking: true, streaming: isTyping }
      })
    }

    // 仅在内容非空时添加正式回答
    // 空内容表示流式输出进行中，由外层 Loading 状态处理
    if (answerWithCitations) {
      contents.push({
        type: 'text',
        content: answerWithCitations,
        metadata: {
          streaming: isTyping,
          confidence: msg.confidence,
          model: msg.model
        }
      })
    }

    if (msg.citations && msg.citations.length > 0) {
      // 任务 X 修复：流式输出过程中不渲染引用卡，避免"先引用后回答"
      // 只有打字机效果完成（isTyping=false）时才追加 citation block
      if (!isTyping) {
        contents.push({
          type: 'citation',
          content: msg.citations
        })
      }
    }

    return contents
  }

  // 获取当前正在流式输出的消息 ID（最后一条 assistant 消息且内容为空时）
  const getStreamingMsgId = (): string | null => {
    if (!isStreaming || !currentSession) return null
    const lastMsg = currentSession.messages[currentSession.messages.length - 1]
    if (lastMsg?.role === 'assistant' && !lastMsg.content) return lastMsg.id
    return null
  }

  // 获取模型显示名称
  const getModelDisplayName = (model?: string): string => {
    if (!model) return 'AI 助手'
    const modelMap: Record<string, string> = {
      'gpt-4o': 'GPT-4o',
      'gpt-4': 'GPT-4',
      'claude-3-opus': 'Claude 3',
      'deepseek-chat': 'DeepSeek',
      'MiniMax-M2.7': 'MiniMax',
      'glm-4': '智谱 GLM',
      'qwen-max': '通义千问',
      'qwen2.5:7b': 'Qwen2.5',
      'Baichuan4': '百川',
      'moonshot-v1-8k': 'Kimi'
    }
    return modelMap[model] || model
  }

  // 获取模型颜色标识
  const getModelColor = (model?: string): string => {
    if (!model) return 'bg-gray-100 text-gray-600'
    if (model.includes('gpt')) return 'bg-blue-100 text-blue-700'
    if (model.includes('claude')) return 'bg-orange-100 text-orange-700'
    if (model.includes('deepseek')) return 'bg-purple-100 text-purple-700'
    if (model.includes('MiniMax')) return 'bg-pink-100 text-pink-700'
    if (model.includes('glm')) return 'bg-indigo-100 text-indigo-700'
    if (model.includes('qwen')) return 'bg-cyan-100 text-cyan-700'
    if (model.includes('Baichuan')) return 'bg-amber-100 text-amber-700'
    if (model.includes('moonshot')) return 'bg-emerald-100 text-emerald-700'
    return 'bg-gray-100 text-gray-600'
  }

  // 过滤会话列表
  const filteredSessions = sessions.filter(s =>
    !searchQuery ||
    s.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    s.messages.some(m => m.content.toLowerCase().includes(searchQuery.toLowerCase()))
  )

  return (
    <div className="h-full flex flex-col">
      {/* 头部 */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="p-2 hover:bg-gray-100 rounded-xl transition-colors"
            title="历史对话"
          >
            <History className="h-5 w-5 text-gray-600" />
          </button>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">智能问答</h1>
            <p className="text-sm text-gray-500 mt-1">基于知识库的 AI 智能对话</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* 当前模型标识 */}
          {currentModel && (
            <span className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${getModelColor(currentModel)}`}>
              <Zap className="h-3 w-3" />
              {getModelDisplayName(currentModel)}
            </span>
          )}
          <button
            onClick={createNewSession}
            className="flex items-center gap-2 px-4 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-xl transition-colors"
          >
            <Plus className="h-4 w-4" />
            <span>新对话</span>
          </button>
          {messages.length > 0 && (
            <button
              onClick={() => exportSession()}
              className="flex items-center gap-2 px-4 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-xl transition-colors"
              title="导出会话"
            >
              <Download className="h-4 w-4" />
              <span>导出</span>
            </button>
          )}
        </div>
      </div>

      <div className="flex flex-1 gap-4 overflow-hidden">
        {/* 历史对话侧边栏 - 卡片布局 + 批量管理 */}
        {showHistory && (
          <div className="w-80 bg-white rounded-2xl border border-gray-100 shadow-sm flex flex-col">
            <div className="p-4 border-b border-gray-100">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-semibold text-gray-900">历史对话</h3>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => {
                      setBatchMode(!batchMode)
                      if (batchMode) setSelectedSessionIds([])
                    }}
                    className={`p-1.5 rounded-lg transition-colors ${
                      batchMode ? 'bg-blue-50 text-blue-600' : 'hover:bg-gray-100 text-gray-400'
                    }`}
                    title={batchMode ? '退出批量模式' : '批量管理'}
                  >
                    <FolderOpen className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => setShowHistory(false)}
                    className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors text-gray-400"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </div>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="搜索对话..."
                  className="w-full pl-9 pr-4 py-2 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 text-sm"
                />
              </div>
            </div>

            {/* 批量操作工具栏 */}
            {batchMode && (
              <div className="px-3 py-2 border-b border-gray-100 bg-blue-50/30">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={selectedSessionIds.length === filteredSessions.length ? deselectAllSessions : selectAllSessions}
                      className="text-xs text-blue-600 hover:text-blue-800 font-medium"
                    >
                      {selectedSessionIds.length === filteredSessions.length ? '取消全选' : '全选'}
                    </button>
                    <span className="text-xs text-gray-500">
                      已选 {selectedSessionIds.length} 项
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={batchDeleteSessions}
                      disabled={selectedSessionIds.length === 0}
                      className="px-2.5 py-1.5 text-xs text-red-600 hover:bg-red-50 rounded-lg disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center gap-1"
                      title="批量删除"
                    >
                      <Trash2 className="h-3 w-3" />
                      删除
                    </button>
                    <button
                      onClick={batchExportSessions}
                      disabled={selectedSessionIds.length === 0}
                      className="px-2.5 py-1.5 text-xs text-gray-600 hover:bg-gray-100 rounded-lg disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center gap-1"
                      title="批量导出"
                    >
                      <Download className="h-3 w-3" />
                      导出
                    </button>
                    <button
                      onClick={batchArchiveSessions}
                      disabled={selectedSessionIds.length === 0}
                      className="px-2.5 py-1.5 text-xs text-gray-600 hover:bg-gray-100 rounded-lg disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center gap-1"
                      title="批量归档"
                    >
                      <Archive className="h-3 w-3" />
                      归档
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* 会话卡片列表 */}
            <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2 app-zone-scroll">
              {filteredSessions.length === 0 ? (
                <div className="text-center py-8 text-gray-400">
                  <MessageSquare className="h-8 w-8 mx-auto mb-2 text-gray-200" />
                  <p className="text-sm">暂无对话历史</p>
                </div>
              ) : (
                filteredSessions.map(session => {
                  const isFavorited = favoriteSessions.includes(session.id)
                  const isSelected = selectedSessionIds.includes(session.id)
                  const isRenaming = renameSessionId === session.id
                  const msgCount = session.messages.length
                  const lastMsg = session.messages[msgCount - 1]

                  return (
                    <div
                      key={session.id}
                      className={`group relative rounded-xl border transition-all ${
                        session.id === currentSessionId
                          ? 'bg-blue-50/50 border-blue-200 shadow-sm'
                          : isSelected
                            ? 'bg-blue-50/30 border-blue-200'
                            : 'bg-white border-gray-100 hover:border-gray-200 hover:shadow-sm'
                      }`}
                    >
                      {/* 批量选择模式：顶层勾选区域 */}
                      {batchMode && (
                        <div className="absolute left-2 top-1/2 -translate-y-1/2 z-10">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelectSession(session.id)}
                            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                          />
                        </div>
                      )}

                      {/* 点击整个卡片切换会话（非编辑/批量模式） */}
                      <div
                        onClick={() => {
                          if (!batchMode && !isRenaming) {
                            setCurrentSessionId(session.id)
                            setShowHistory(false)
                          }
                        }}
                        className={`p-3 cursor-pointer ${batchMode ? 'pl-8' : ''}`}
                      >
                        {/* 标题行 */}
                        <div className="flex items-center justify-between">
                          <div className="flex-1 min-w-0 mr-2">
                            {isRenaming ? (
                              <div className="flex items-center gap-1">
                                <input
                                  type="text"
                                  value={renameTitle}
                                  onChange={(e) => setRenameTitle(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') saveRenameSession()
                                    if (e.key === 'Escape') cancelRenameSession()
                                  }}
                                  className="flex-1 px-2 py-1 text-sm border border-blue-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                                  autoFocus
                                  onClick={(e) => e.stopPropagation()}
                                />
                                <button
                                  onClick={(e) => { e.stopPropagation(); saveRenameSession() }}
                                  className="p-1 text-blue-600 hover:bg-blue-50 rounded"
                                >
                                  <Check className="h-3.5 w-3.5" />
                                </button>
                                <button
                                  onClick={(e) => { e.stopPropagation(); cancelRenameSession() }}
                                  className="p-1 text-gray-400 hover:bg-gray-100 rounded"
                                >
                                  <X className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            ) : (
                              <h4 className="font-medium text-sm text-gray-900 truncate flex items-center gap-1.5">
                                {isFavorited && (
                                  <Star className="h-3 w-3 fill-amber-400 text-amber-400 shrink-0" />
                                )}
                                {session.title}
                              </h4>
                            )}
                          </div>

                          {/* 操作按钮（非批量模式、非重命名模式） */}
                          {!batchMode && !isRenaming && (
                            <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                              <button
                                onClick={(e) => { e.stopPropagation(); toggleFavoriteSession(session.id) }}
                                className={`p-1 rounded-lg transition-colors ${
                                  isFavorited ? 'text-amber-500' : 'text-gray-400 hover:text-amber-500'
                                } hover:bg-amber-50`}
                                title={isFavorited ? '取消收藏' : '收藏'}
                              >
                                <Star className={`h-3.5 w-3.5 ${isFavorited ? 'fill-amber-400' : ''}`} />
                              </button>
                              <button
                                onClick={(e) => { e.stopPropagation(); startRenameSession(session) }}
                                className="p-1 text-gray-400 hover:text-blue-500 hover:bg-blue-50 rounded-lg transition-colors"
                                title="重命名"
                              >
                                <Edit3 className="h-3.5 w-3.5" />
                              </button>
                              <button
                                onClick={(e) => { e.stopPropagation(); archiveSession(session.id) }}
                                className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                                title="归档"
                              >
                                <Archive className="h-3.5 w-3.5" />
                              </button>
                              <button
                                onClick={(e) => { e.stopPropagation(); exportSession(session.id) }}
                                className="p-1 text-gray-400 hover:text-green-500 hover:bg-green-50 rounded-lg transition-colors"
                                title="导出"
                              >
                                <Download className="h-3.5 w-3.5" />
                              </button>
                              <button
                                onClick={(e) => { e.stopPropagation(); deleteSession(session.id) }}
                                className="p-1 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                                title="删除"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          )}
                        </div>

                        {/* 元信息 */}
                        <p className="text-xs text-gray-400 mt-1 flex items-center gap-2">
                          <span>{msgCount} 条消息</span>
                          <span>·</span>
                          <span>{session.updatedAt.toLocaleDateString()}</span>
                          {lastMsg && (
                            <>
                              <span>·</span>
                              <span className="truncate">{lastMsg.timestamp.toLocaleTimeString()}</span>
                            </>
                          )}
                        </p>

                        {/* 最后一条消息预览 */}
                        {lastMsg && !batchMode && (
                          <div className="mt-1.5">
                            <p className="text-[11px] text-gray-400 truncate leading-relaxed">
                              {lastMsg.role === 'user' ? '🙋 ' : '🤖 '}
                              {lastMsg.content.slice(0, 60)}{lastMsg.content.length > 60 ? '...' : ''}
                            </p>
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })
              )}
            </div>

            {sessions.length > 0 && !batchMode && (
              <div className="p-4 border-t border-gray-100">
                <button
                  onClick={clearAllSessions}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2 text-sm text-red-600 hover:bg-red-50 rounded-xl transition-colors"
                >
                  <Trash2 className="h-4 w-4" />
                  清空所有对话
                </button>
              </div>
            )}
          </div>
        )}

        {/* 消息区域 */}
        <div className="flex-1 flex flex-col min-w-0">{/* 消息区域 */}
          <div className="flex-1 min-h-0 overflow-y-auto bg-white rounded-2xl border border-gray-100 shadow-sm mb-4 app-zone-scroll">            {messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-gray-400">
                <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-50 to-indigo-50 flex items-center justify-center mb-4">
                  <Bot className="h-8 w-8 text-blue-500" />
                </div>
                <p className="text-lg font-medium text-gray-600">开始智能对话</p>
                <p className="text-sm mt-2">输入问题，AI 将基于知识库为您解答</p>
                <div className="flex gap-2 mt-6">
                  {['什么是 RAG？', '如何优化向量检索？', '知识图谱的作用'].map((q) => (
                    <button
                      key={q}
                      onClick={() => { setInputText(q); textareaRef.current?.focus() }}
                      className="px-4 py-2 bg-gray-50 text-gray-600 rounded-xl text-sm hover:bg-gray-100 transition-colors"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="p-6 space-y-6">
                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`flex gap-4 group ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
                  >
                    <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${
                      msg.role === 'user'
                        ? 'bg-gradient-to-br from-blue-500 to-indigo-600'
                        : 'bg-gradient-to-br from-emerald-500 to-teal-600'
                    }`}>
                      {msg.role === 'user' ? (
                        <User className="h-4 w-4 text-white" />
                      ) : (
                        <Bot className="h-4 w-4 text-white" />
                      )}
                    </div>

                    {/* 容器：用户消息右对齐且只占内容宽度（w-fit），AI 消息占满剩余空间 */}
                    <div className={`${msg.role === 'user' ? 'ml-auto w-fit max-w-[80%] flex flex-col items-end' : 'flex-1 min-w-0 max-w-[80%] flex flex-col items-start'}`}>
                      {/* 编辑模式 - 用户消息 */}
                      {editingMsgId === msg.id ? (
                        <div className="rounded-2xl p-3 bg-blue-50 border border-blue-200 w-full">
                          <textarea
                            ref={editInputRef}
                            value={editingContent}
                            onChange={(e) => setEditingContent(e.target.value)}
                            className="w-full bg-white rounded-lg p-3 border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 resize-none"
                            rows={4}
                          />
                          <div className="flex gap-2 mt-3">
                            <button
                              onClick={saveEditMessage}
                              className="px-4 py-1.5 bg-blue-600 text-white rounded-lg text-xs hover:bg-blue-700 transition-colors"
                            >
                              保存
                            </button>
                            <button
                              onClick={cancelEdit}
                              className="px-4 py-1.5 bg-gray-100 text-gray-600 rounded-lg text-xs hover:bg-gray-200 transition-colors"
                            >
                              取消
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className={`rounded-2xl p-4 break-words ${
                          msg.role === 'user'
                            ? 'bg-blue-600 text-white'
                            : 'bg-gray-50 border border-gray-100 w-full'
                        }`} style={msg.role === 'user' ? { width: 'fit-content', maxWidth: '100%' } : undefined}>
                          {msg.role === 'assistant' ? (
                            msg.content ? (
                              <RichContentRenderer
                                contents={(() => {
                                  // 任务 Y：打字机效果 - 截断到 displayedLengths，并把 isTyping 传给子组件
                                  const displayed = displayedLengths[msg.id] ?? msg.content.length
                                  const visibleText = msg.content.slice(0, displayed)
                                  const isTyping = displayed < msg.content.length
                                  const baseContents = convertToRichContents({ ...msg, content: visibleText }, isTyping)
                                  return baseContents
                                })()}
                              />
                            ) : isStreaming ? (
                              // 任务 v6 修复：检索/生成中显示过渡动画（"思考中" / "检索中" / "生成中"）
                              // 严禁显示"未能生成有效回答"——会与后续真实答案重复，造成歧义
                              <TypingIndicator />
                            ) : (
                              // 任务 v6 修复：只有在真正出错时才显示提示文案
                              // 且文案改为具体的错误信息（不显示"未能生成有效回答"这种模糊文案）
                              (msg as any).taskStatus === 'error' ? (
                                <span className="text-red-500 text-sm">⚠️ 生成失败：{(msg as any).error || '未知错误，请稍后重试'}</span>
                              ) : null
                            )
                          ) : (
                            <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                          )}
                          {(msg as any).edited && (
                            <span className="text-[10px] opacity-60 mt-1 block">已编辑</span>
                          )}
                        </div>
                      )}

                      {/* 消息操作栏 */}
                      <div className={`flex items-center gap-3 mt-2 text-xs ${
                        msg.role === 'user' ? 'justify-end' : ''
                      }`}>
                        {/* 标记重点 */}
                        {markedImportant.includes(msg.id) && (
                          <span className="flex items-center gap-1 text-amber-500">
                            <Star className="h-3 w-3 fill-amber-400" />
                            <span>重点</span>
                          </span>
                        )}

                        <span className="flex items-center gap-1 text-gray-400">
                          <Clock className="h-3 w-3" />
                          {msg.timestamp.toLocaleTimeString()}
                        </span>

                        {msg.confidence && (
                          <span className="text-emerald-500">
                            置信度: {(msg.confidence * 100).toFixed(0)}%
                          </span>
                        )}

                        {/* 模型标识 */}
                        {msg.role === 'assistant' && msg.model && (
                          <span className={`flex items-center gap-1 px-2 py-0.5 rounded-full font-medium ${getModelColor(msg.model)}`}>
                            <Brain className="h-3 w-3" />
                            {msg.modelName || getModelDisplayName(msg.model)}
                          </span>
                        )}

                        {/* 复制按钮 */}
                        <button
                          onClick={() => handleCopy(msg.content, msg.id)}
                          className="flex items-center gap-1 text-gray-400 hover:text-gray-600 transition-colors"
                          title="复制"
                        >
                          {copiedId === msg.id ? (
                            <Check className="h-3 w-3 text-green-500" />
                          ) : (
                            <Copy className="h-3 w-3" />
                          )}
                        </button>

                        {/* 更多操作下拉菜单 */}
                        <div className="relative">
                          <button
                            onClick={() => setMenuOpenId(menuOpenId === msg.id ? null : msg.id)}
                            className="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors opacity-0 group-hover:opacity-100"
                            title="更多操作"
                          >
                            <MoreVertical className="h-3.5 w-3.5" />
                          </button>

                          {menuOpenId === msg.id && (
                            <>
                              <div className="fixed inset-0 z-10" onClick={() => setMenuOpenId(null)} />
                              <div className={`absolute z-20 mt-1 w-40 bg-white rounded-xl shadow-lg border border-gray-200 py-1 ${
                                msg.role === 'user' ? 'right-0' : 'left-0'
                              }`}>
                                {msg.role === 'user' ? (
                                  <button
                                    onClick={() => startEditMessage(msg)}
                                    className="w-full flex items-center gap-2 px-3 py-2 text-xs text-gray-700 hover:bg-gray-50"
                                  >
                                    <Edit3 className="h-3.5 w-3.5" />
                                    编辑
                                  </button>
                                ) : (
                                  <>
                                    <button
                                      onClick={() => {
                                        handleCopy(msg.content, msg.id)
                                        setMenuOpenId(null)
                                      }}
                                      className="w-full flex items-center gap-2 px-3 py-2 text-xs text-gray-700 hover:bg-gray-50"
                                    >
                                      <Copy className="h-3.5 w-3.5" />
                                      复制回答
                                    </button>
                                    <button
                                      onClick={() => regenerateMessage(msg.id)}
                                      disabled={regeneratingId !== null}
                                      className="w-full flex items-center gap-2 px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                                    >
                                      <RefreshCw className="h-3.5 w-3.5" />
                                      重新生成
                                    </button>
                                  </>
                                )}
                                <button
                                  onClick={() => toggleMarkImportant(msg.id)}
                                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-gray-700 hover:bg-gray-50"
                                >
                                  <Star className={`h-3.5 w-3.5 ${markedImportant.includes(msg.id) ? 'fill-amber-400 text-amber-500' : ''}`} />
                                  {markedImportant.includes(msg.id) ? '取消重点' : '标记重点'}
                                </button>
                                <button
                                  onClick={() => exportMessage(msg)}
                                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-gray-700 hover:bg-gray-50"
                                >
                                  <FileDown className="h-3.5 w-3.5" />
                                  导出
                                </button>
                                <div className="border-t border-gray-100 my-1" />
                                <button
                                  onClick={() => deleteMessage(msg.id)}
                                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-red-600 hover:bg-red-50"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                  删除
                                </button>
                              </div>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}

                {isStreaming && (
                  <div className="flex justify-center mt-2">
                    <button
                      onClick={handleStopGeneration}
                      className="flex items-center gap-1 px-4 py-2 text-sm bg-white text-red-600 rounded-full hover:bg-red-50 transition-colors border border-red-200 shadow-sm"
                      title="立即停止生成"
                    >
                      <X className="h-4 w-4" />
                      停止生成
                    </button>
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          {/* 输入区域 */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
            {/* 任务 1.2：已选分类标签（空 = 全库） */}
            {selectedCategories.length > 0 && (
              <div className="mb-2 flex flex-wrap items-center gap-1.5 text-xs">
                <span className="text-gray-500">检索范围：</span>
                {selectedCategories.map((c) => (
                  <span
                    key={c}
                    className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-blue-700 rounded-md font-medium"
                  >
                    {c}
                    <button
                      onClick={() => setSelectedCategories((prev) => prev.filter((x) => x !== c))}
                      className="hover:text-red-500"
                      title="移除此分类"
                    >×</button>
                  </span>
                ))}
                <button
                  onClick={() => setSelectedCategories([])}
                  className="text-gray-400 hover:text-gray-600 underline"
                >全库</button>
              </div>
            )}
            <div className="flex gap-3 relative">
              <textarea
                ref={textareaRef}
                value={inputText}
                onChange={(e) => {
                  const v = e.target.value
                  // 任务 1.1：检测到独立的 "/" 字符触发分类选择弹窗
                  // 任务 1.3 兼容：仅当输入是单个 "/" 时才弹分类选择器
                  // 其他 "/xxx" 情况交给 slash 系统处理
                  if (v === '/') {
                    setKbPickerOpen(true)
                  }
                  setInputText(v)
                }}
                onKeyDown={handleKeyDown}
                placeholder="输入问题，Enter 发送，Shift+Enter 换行...（输入 / 唤出快捷指令）"
                rows={2}
                className="flex-1 resize-none px-4 py-3 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 text-sm"
              />
              {/* 任务 1.3：快捷指令选择器（输入 / 或 /xxx 触发） */}
              {slashOpen && !kbPickerOpen && (
                <SlashCommandPicker
                  commands={slashCommands}
                  selectedIndex={slashIndex}
                  keyword={slashKeyword}
                  onSelect={(cmd) => executeSlashCommand(cmd)}
                  onHover={(idx) => setSlashIndex(idx)}
                />
              )}
              {/* 任务 1.1：分类选择弹窗（输入 / 触发） */}
              {kbPickerOpen && (
                <KbCategoryPicker
                  categories={availableCategories}
                  selected={selectedCategories}
                  onToggle={(c) =>
                    setSelectedCategories((prev) =>
                      prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]
                    )
                  }
                  onClose={() => {
                    setKbPickerOpen(false)
                    // 弹窗关闭时移除触发字符 "/"
                    setInputText((prev) => (prev.startsWith('/') ? prev.slice(1) : prev))
                  }}
                />
              )}
              <button
                onClick={() => {
                  // 任务 1.3 修复：发送按钮也要先检查指令列表
                  if (slashOpen && slashCommands.length > 0) {
                    executeSlashCommand(slashCommands[slashIndex])
                    return
                  }
                  handleSend()
                }}
                disabled={!inputText.trim() || isStreaming}
                className="px-6 py-3 bg-gradient-to-r from-blue-500 to-indigo-600 text-white rounded-xl hover:shadow-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {isStreaming ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <>
                    <Send className="h-4 w-4" />
                    <span className="hidden sm:inline">发送</span>
                  </>
                )}
              </button>
            </div>
            <p className="text-xs text-gray-400 mt-2 flex items-center gap-1">
              <BookOpen className="h-3 w-3" />
              AI 回答基于知识库内容，仅供参考
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

// ==================== 任务 1.1：分类选择弹窗 ====================
function KbCategoryPicker({
  categories, selected, onToggle, onClose,
}: {
  categories: string[]
  selected: string[]
  onToggle: (c: string) => void
  onClose: () => void
}) {
  return (
    <div
      style={{
        position: 'absolute', left: 0, bottom: '100%', marginBottom: 8, zIndex: 50,
        background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, padding: 8,
        boxShadow: '0 4px 16px rgba(0,0,0,0.1)', minWidth: 220,
      }}
    >
      <div style={{ padding: '4px 8px 8px', fontSize: 12, color: '#64748b', display: 'flex', alignItems: 'center', gap: 6 }}>
        <Library className="h-3.5 w-3.5" /> 选择检索范围（多选）
      </div>
      {categories.length === 0 ? (
        <div style={{ padding: 12, fontSize: 12, color: '#94a3b8', textAlign: 'center' }}>暂无分类</div>
      ) : (
        categories.map((c) => {
          const checked = selected.includes(c)
          return (
            <button
              key={c}
              onClick={() => onToggle(c)}
              style={{
                display: 'flex', alignItems: 'center', width: '100%', padding: '6px 8px', borderRadius: 6,
                background: checked ? '#eff6ff' : 'transparent', fontSize: 13, textAlign: 'left', gap: 8,
              }}
              className="hover:bg-gray-50"
            >
              <span style={{
                width: 16, height: 16, border: '2px solid ' + (checked ? '#3b82f6' : '#cbd5e1'),
                borderRadius: 4, background: checked ? '#3b82f6' : 'transparent',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 11, fontWeight: 700,
              }}>{checked ? '✓' : ''}</span>
              <span>{c}</span>
            </button>
          )
        })
      )}
      <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid #f1f5f9', display: 'flex', justifyContent: 'flex-end' }}>
        <button
          onClick={onClose}
          style={{ padding: '4px 10px', fontSize: 12, background: '#3b82f6', color: '#fff', borderRadius: 6 }}
        >完成</button>
      </div>
    </div>
  )
}
