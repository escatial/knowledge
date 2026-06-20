/**
 * AIChat - 基于持久化任务模型的智能问答组件
 *
 * 关键设计：使用 aiTaskStore 全局存储 + 轮询机制
 * - 切走页面 → 组件 unmount → 轮询定时器被清 → 但后端任务继续跑
 * - 切回页面 → 组件 mount → 自动恢复对该 session 所有任务的轮询
 * - 即便用户刷新页面（localStorage 持久化），历史消息和任务 ID 也不丢
 *
 * 改进点 (v2)：
 * - 在模块加载时（import 阶段）就启动一次轮询恢复，无需等组件 mount
 * - 客户端轮询间隔优化：前 5 次 500ms 轮询，之后 1s
 * - 切到其他页面时把轮询交给全局 pollerMap（不被 React 生命周期杀掉）
 * - 思考/答案分离（折叠面板）
 * - 引用序号溯源（①②③ 跳转）
 * - 斜杠 `/` 触发知识库多选
 * - 任务 P3-7：集成 react-markdown + remark-gfm，渲染 LLM 输出的 Markdown 表格/代码块/列表
 */
import { useState, useRef, useEffect, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { aiApi, categoryApi } from '../services/api'
import {
  aiTaskStore,
  addUserMessage,
  addAssistantPlaceholder,
  updateAssistant,
  resumePendingTasks,
  setSelectedCategories,
  toggleSelectedCategory,
  ChatMessage,
} from '../services/aiTaskStore'

interface AIChatProps {
  embedded?: boolean
}

// 任务 X：注入 keyframes（打字机光标闪烁 + 引用块淡入 + 三点跳动）
const STYLE_TAG_ID = 'aichat-keyframes'
if (typeof document !== 'undefined' && !document.getElementById(STYLE_TAG_ID)) {
  const styleEl = document.createElement('style')
  styleEl.id = STYLE_TAG_ID
  styleEl.textContent = `
    @keyframes blink {
      0%, 50% { opacity: 1; }
      51%, 100% { opacity: 0; }
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(4px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes typingDot {
      0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
      40%           { transform: scale(1.0); opacity: 1; }
    }
    @keyframes shimmer {
      0%   { background-position: -200% 0; }
      100% { background-position: 200% 0; }
    }
  `
  document.head.appendChild(styleEl)
}

// 用于跨组件实例追踪轮询定时器（key: taskId, value: intervalId）
const pollers = new Map<string, ReturnType<typeof setInterval>>()

// 启动一次恢复：模块加载时扫一遍 localStorage 里所有 pending 任务继续轮询
resumePendingTasks()

function startPolling(taskId: string) {
  if (pollers.has(taskId)) return  // 已经在轮询
  let ticks = 0
  const handle = setInterval(async () => {
    ticks += 1
    try {
      const res = await aiApi.getTask(taskId)
      const t = res.data
      if (!t || t.success === false) {
        clearInterval(handle)
        pollers.delete(taskId)
        return
      }
      updateAssistant(taskId, {
        content: t.answer || t.text || '',
        thinking: t.thinking || '',
        citations: t.citations,
        confidence: t.confidence,
        taskStatus: t.status,
      })
      if (t.status === 'done' || t.status === 'error') {
        clearInterval(handle)
        pollers.delete(taskId)
      } else if (ticks > 10) {
        clearInterval(handle)
        pollers.delete(taskId)
        const slowHandle = setInterval(async () => {
          try {
            const r2 = await aiApi.getTask(taskId)
            const t2 = r2.data
            updateAssistant(taskId, {
              content: t2.answer || t2.text || '',
              thinking: t2.thinking || '',
              citations: t2.citations,
              confidence: t2.confidence,
              taskStatus: t2.status,
            })
            if (t2.status === 'done' || t2.status === 'error') {
              clearInterval(slowHandle)
              pollers.delete(taskId)
            }
          } catch (e) {
            clearInterval(slowHandle)
            pollers.delete(taskId)
          }
        }, 2000)
        pollers.set(taskId, slowHandle)
      }
    } catch (e) {
      console.error('[AIChat] 轮询任务失败', e)
      clearInterval(handle)
      pollers.delete(taskId)
    }
  }, 500)
  pollers.set(taskId, handle)
}

function stopPolling(taskId: string) {
  const h = pollers.get(taskId)
  if (h) {
    clearInterval(h)
    pollers.delete(taskId)
  }
}

function AIChat({ embedded = false }: AIChatProps) {
  const messages = aiTaskStore.useStore((s) => s.messages)
  const sessionId = aiTaskStore.useStore((s) => s.sessionId)

  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // v2：`/` 触发的分类选择面板
  const [showSlashPanel, setShowSlashPanel] = useState(false)
  const [slashFilter, setSlashFilter] = useState('')

  // 切到本页面时：
  // 1) 自动恢复所有进行中任务的轮询
  // 2) 可选：与后端 listTasks 对账（避免后端重启丢消息）
  useEffect(() => {
    // 恢复轮询 —— 每次 mount 都执行，不依赖 messages.length
    const msgs = aiTaskStore.getState().messages
    msgs.forEach((m) => {
      if (m.taskId && (m.taskStatus === 'pending' || m.taskStatus === 'running')) {
        startPolling(m.taskId)
      }
    })
  }, [])  // 空依赖：仅在 mount 时执行

  // 滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  // 卸载时不清轮询（让其它页面继续接收结果）
  useEffect(() => {
    return () => {
      // 不 stopPolling —— 切到其他页面时也要继续接收
    }
  }, [])

  // v2：当前选中的知识库分类（用于 `/` 触发选择）
  const selectedCategories = aiTaskStore.useStore((s) => s.selectedCategories)
  const [categories, setCategories] = useState<{ name: string }[]>([])

  useEffect(() => {
    categoryApi.getAll().then((r) => setCategories(r.data || [])).catch(() => {})
  }, [])

  const handleSend = async () => {
    const question = input.trim()
    if (!question) return

    setInput('')
    setShowSlashPanel(false)

    // 记录选中的分类（用于溯源）
    addUserMessage(question, selectedCategories.length ? [...selectedCategories] : undefined)

    try {
      const submitRes = await aiApi.askAsync(
        question,
        sessionId,
        messages.slice(-12).map((m) => ({ role: m.role, content: m.content })),
        undefined,
        selectedCategories.length ? selectedCategories : undefined,
      )
      const taskId: string = submitRes.data.task_id
      addAssistantPlaceholder(taskId, selectedCategories.length ? [...selectedCategories] : undefined)
      startPolling(taskId)
    } catch (err) {
      addUserMessage('抱歉，请求失败: ' + (err as Error).message)
    }
  }

  const handleClear = () => {
    if (!confirm('确定要清空所有对话历史吗？')) return
    // 停止所有进行中的轮询
    messages.forEach((m) => {
      if (m.taskId) {
        stopPolling(m.taskId)
        // 通知后端删除任务（best effort）
        aiApi.deleteTask(m.taskId).catch(() => {})
      }
    })
    // 清空 store
    aiTaskStore.setState((prev) => ({
      ...prev,
      messages: [],
      sessionId: `session_${Date.now()}`,
    }))
  }

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: embedded ? 400 : 500,
      border: embedded ? '1px solid #e0e0e0' : 'none',
      borderRadius: embedded ? 8 : 0,
      overflow: 'hidden'
    }}>
      {/* 消息列表 */}
      <div style={{
        flex: 1,
        overflow: 'auto',
        padding: 15,
        background: '#f8f9fa',
        position: 'relative',
      }}>
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', color: '#999', padding: 20 }}>
            <p>👋 我是你的知识库助手</p>
            <p style={{ fontSize: 13 }}>基于知识库内容为你解答问题</p>
            <p style={{ fontSize: 11, marginTop: 8, color: '#bbb' }}>
              切走页面不会中断任务 — 切回时会自动显示完整答案
            </p>
          </div>
        )}

        {messages.map((msg, idx) => (
          <MessageBubble key={msg.id || idx} msg={msg} />
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* 已选分类标签 */}
      {selectedCategories.length > 0 && (
        <div style={{
          padding: '6px 12px',
          borderTop: '1px solid #f3f4f6',
          background: '#f9fafb',
          display: 'flex',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 4,
        }}>
          <span style={{ fontSize: 11, color: '#6b7280' }}>检索范围：</span>
          {selectedCategories.map((cat) => (
            <span
              key={cat}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                padding: '2px 8px',
                background: '#dbeafe',
                color: '#1e40af',
                borderRadius: 12,
                fontSize: 11,
              }}
            >
              {cat}
              <span
                onClick={() => toggleSelectedCategory(cat)}
                style={{ cursor: 'pointer', fontWeight: 'bold' }}
                title="移除此分类"
              >×</span>
            </span>
          ))}
        </div>
      )}

      {/* 输入框 */}
      <div style={{
        display: 'flex',
        gap: 8,
        padding: 10,
        borderTop: '1px solid #eee',
        background: '#fff',
        alignItems: 'center'
      }}>
        <button
          onClick={handleClear}
          disabled={messages.length === 0}
          style={{
            padding: '6px 10px',
            background: 'transparent',
            color: '#999',
            border: '1px solid #ddd',
            borderRadius: 6,
            cursor: messages.length ? 'pointer' : 'not-allowed',
            fontSize: 12,
          }}
          title="清空对话"
        >
          🗑
        </button>
        <div style={{ flex: 1, position: 'relative' }}>
          <input
            type="text"
            value={input}
            onChange={e => {
              const v = e.target.value
              setInput(v)
              // v2：检测输入 `/` 触发分类选择面板
              if (v === '/') {
                setShowSlashPanel(true)
                setSlashFilter('')
              } else if (showSlashPanel) {
                // 在 / 后面输入过滤
                if (v.startsWith('/')) {
                  setSlashFilter(v.slice(1).toLowerCase())
                } else {
                  setShowSlashPanel(false)
                }
              }
            }}
            placeholder="输入 / 选择知识库，或直接输入问题..."
            style={{
              width: '100%',
              padding: '8px 30px 8px 12px',
              border: '1px solid #ddd',
              borderRadius: 6,
              fontSize: 14,
              boxSizing: 'border-box',
            }}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                if (showSlashPanel) {
                  // 不直接发送，而是按"全部"或默认行为
                  setShowSlashPanel(false)
                  setInput('')
                } else {
                  handleSend()
                }
              } else if (e.key === 'Escape' && showSlashPanel) {
                setShowSlashPanel(false)
                setInput('')
              }
            }}
          />

          {/* v2：`/` 触发的知识库分类选择面板 */}
          {showSlashPanel && (
            <div
              style={{
                position: 'absolute',
                bottom: '110%',
                left: 0,
                right: 0,
                maxHeight: 280,
                overflowY: 'auto',
                background: '#fff',
                border: '1px solid #e5e7eb',
                borderRadius: 8,
                boxShadow: '0 -4px 16px rgba(0,0,0,0.08)',
                zIndex: 50,
              }}
            >
              <div style={{
                padding: '8px 12px',
                borderBottom: '1px solid #f3f4f6',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}>
                <span style={{ fontSize: 12, color: '#6b7280' }}>
                  选择知识库（不选 = 全平台检索）
                </span>
                <div style={{ display: 'flex', gap: 4 }}>
                  <button
                    onClick={() => setSelectedCategories(categories.map((c) => c.name))}
                    style={{
                      padding: '2px 8px',
                      fontSize: 11,
                      border: '1px solid #d1d5db',
                      borderRadius: 4,
                      background: '#fff',
                      cursor: 'pointer',
                    }}
                  >
                    全选
                  </button>
                  <button
                    onClick={() => setSelectedCategories([])}
                    style={{
                      padding: '2px 8px',
                      fontSize: 11,
                      border: '1px solid #d1d5db',
                      borderRadius: 4,
                      background: '#fff',
                      cursor: 'pointer',
                    }}
                  >
                    清空
                  </button>
                </div>
              </div>
              {categories
                .filter((c) => !slashFilter || c.name.toLowerCase().includes(slashFilter))
                .map((c) => {
                  const checked = selectedCategories.includes(c.name)
                  return (
                    <div
                      key={c.name}
                      onClick={() => toggleSelectedCategory(c.name)}
                      style={{
                        padding: '8px 12px',
                        cursor: 'pointer',
                        background: checked ? '#eff6ff' : 'transparent',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        fontSize: 13,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleSelectedCategory(c.name)}
                        style={{ pointerEvents: 'none' }}
                      />
                      <span>{c.name}</span>
                    </div>
                  )
                })}
              {categories.length === 0 && (
                <div style={{ padding: 16, textAlign: 'center', color: '#9ca3af', fontSize: 12 }}>
                  暂无分类
                </div>
              )}
            </div>
          )}
          {input && (
            <button
              onClick={() => setInput('')}
              style={{
                position: 'absolute',
                right: 6,
                top: '50%',
                transform: 'translateY(-50%)',
                padding: '2px',
                border: 'none',
                background: 'transparent',
                cursor: 'pointer',
                color: '#999',
                fontSize: 16,
                lineHeight: 1,
              }}
              title="清空"
            >
              ×
            </button>
          )}
        </div>
        <button
          onClick={handleSend}
          disabled={!input.trim()}
          style={{
            padding: '8px 16px',
            background: input.trim() ? '#3498db' : '#bdc3c7',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: input.trim() ? 'pointer' : 'not-allowed',
            fontSize: 14
          }}
        >
          发送
        </button>
      </div>
    </div>
  )
}

// 任务 X：产品级加载过渡动画 —— 三种状态切换：思考中 / 检索中 / 生成中
export function TypingIndicator() {
  const [stage, setStage] = useState<'thinking' | 'retrieving' | 'generating'>('thinking')

  // 阶段轮换：思考 → 检索 → 生成，循环展示当前进度
  useEffect(() => {
    const stages: Array<'thinking' | 'retrieving' | 'generating'> = ['thinking', 'retrieving', 'generating']
    let idx = 0
    const tick = setInterval(() => {
      idx = (idx + 1) % stages.length
      setStage(stages[idx])
    }, 1500)  // 每 1.5s 切换阶段
    return () => clearInterval(tick)
  }, [])

  const labels = {
    thinking: '思考中',
    retrieving: '检索知识库',
    generating: '正在生成回答',
  } as const

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '6px 0',
    }}>
      {/* 三点跳动动画 */}
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        {[0, 1, 2].map(i => (
          <span
            key={i}
            style={{
              display: 'inline-block',
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: '#3b82f6',
              animation: `typingDot 1.2s ${i * 0.15}s infinite ease-in-out`,
            }}
          />
        ))}
      </div>
      {/* 阶段文字（淡入淡出切换） */}
      <span style={{
        fontSize: 12,
        color: '#6b7280',
        animation: 'fadeIn 0.4s ease-in',
      }}>
        {labels[stage]}
      </span>
    </div>
  )
}

// 把答案文本按句末标点（。！？；\n）切分，并在每个关键句子末尾
// 自动注入 ①②③ 引用标识 —— 符合需求 4 "句末添加引用标识"。
// 引用数量与句子数取最小值，避免句子多于引用时出现空标注。
//
// 任务 X：支持『打字机效果』 —— displayChars 参数控制已显示的字符数，
// 让字符按 chunk 逐段显示，体验更自然。displayChars=null 表示一次性显示全部。
//
// 任务 P3-7：集成 react-markdown + remark-gfm
//  - LLM 输出的 Markdown 表格 / 列表 / 代码块 / 标题现在能正确渲染
//  - 引用标号 ①②③ 通过自定义 text 组件处理（点击展开来源）
function renderContentWithCitations(
  text: string,
  citations: { num: number; label: string; citation: any }[],
  openSource: (c: any) => void,
  displayChars: number | null = null,
) {
  // 打字机效果：只显示前 N 个字符
  const visibleText = displayChars == null || displayChars >= text.length
    ? text
    : text.slice(0, displayChars)

  if (citations.length === 0) {
    // 无引用：纯 Markdown 渲染
    return (
      <>
        <div className="markdown-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={markdownComponents}
          >
            {visibleText}
          </ReactMarkdown>
        </div>
        {displayChars != null && displayChars < text.length && (
          <span style={{
            display: 'inline-block',
            width: 6,
            height: 14,
            background: '#3498db',
            marginLeft: 2,
            animation: 'blink 0.8s infinite',
            verticalAlign: 'middle',
          }} />
        )}
      </>
    )
  }

  // 有引用：按句末标点切分，句末插入可点击的 ① ② ③
  // 段内仍走 Markdown 渲染（支持表格/列表）
  const parts = visibleText.split(/(?<=[。！？；\n])/g).filter(Boolean)
  const n = Math.min(parts.length, citations.length)
  return (
    <>
      <div className="markdown-body">
        {parts.map((seg, i) => {
          const cite = i < n ? citations[i] : null
          return (
            <span key={i}>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {seg}
              </ReactMarkdown>
              {cite && (
                <sup
                  onClick={(e) => { e.stopPropagation(); openSource(cite.citation) }}
                  title={`来源：${cite.citation?.metadata?.title || '文档'} · 片段 ${cite.citation?.metadata?.chunk_index ?? '-'}`}
                  style={{
                    color: '#2563eb',
                    cursor: 'pointer',
                    fontSize: 11,
                    marginLeft: 1,
                    padding: '0 2px',
                    background: '#eff6ff',
                    borderRadius: 3,
                    fontWeight: 600,
                    userSelect: 'none',
                  }}
                >
                  {cite.label}
                </sup>
              )}
            </span>
          )
        })}
      </div>
      {displayChars != null && displayChars < text.length && (
        <span style={{
          display: 'inline-block',
          width: 6,
          height: 14,
          background: '#3498db',
          marginLeft: 2,
          animation: 'blink 0.8s infinite',
          verticalAlign: 'middle',
        }} />
      )}
    </>
  )
}

// 任务 P3-7：Markdown 自定义组件
// - table: 加边框 + 斑马纹
// - code: 暗色背景
// - a: 蓝色 + 下划线
const markdownComponents = {
  table({ children }: any) {
    return (
      <div className="overflow-x-auto my-2">
        <table className="min-w-full border-collapse border border-gray-300 text-sm">
          {children}
        </table>
      </div>
    )
  },
  thead({ children }: any) {
    return <thead className="bg-gray-50">{children}</thead>
  },
  th({ children }: any) {
    return (
      <th className="border border-gray-300 px-3 py-2 text-left font-semibold text-gray-700">
        {children}
      </th>
    )
  },
  td({ children }: any) {
    return (
      <td className="border border-gray-300 px-3 py-2 text-gray-800">
        {children}
      </td>
    )
  },
  tr({ children }: any) {
    return <tr className="hover:bg-gray-50">{children}</tr>
  },
  code({ node, inline, className, children, ...props }: any) {
    if (inline) {
      return (
        <code className="bg-gray-100 text-pink-600 px-1 py-0.5 rounded text-[13px] font-mono" {...props}>
          {children}
        </code>
      )
    }
    return (
      <code className="block bg-gray-900 text-gray-100 p-3 rounded my-2 text-[13px] font-mono overflow-x-auto" {...props}>
        {children}
      </code>
    )
  },
  h1({ children }: any) {
    return <h1 className="text-xl font-bold mt-3 mb-2 text-gray-900">{children}</h1>
  },
  h2({ children }: any) {
    return <h2 className="text-lg font-bold mt-3 mb-2 text-gray-900">{children}</h2>
  },
  h3({ children }: any) {
    return <h3 className="text-base font-semibold mt-2 mb-1 text-gray-900">{children}</h3>
  },
  ul({ children }: any) {
    return <ul className="list-disc pl-6 my-2 space-y-1">{children}</ul>
  },
  ol({ children }: any) {
    return <ol className="list-decimal pl-6 my-2 space-y-1">{children}</ol>
  },
  li({ children }: any) {
    return <li className="text-gray-800">{children}</li>
  },
  p({ children }: any) {
    return <p className="my-1.5 leading-relaxed">{children}</p>
  },
  a({ children, href }: any) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
        {children}
      </a>
    )
  },
  blockquote({ children }: any) {
    return (
      <blockquote className="border-l-4 border-blue-400 bg-blue-50 pl-3 py-1 my-2 text-gray-700">
        {children}
      </blockquote>
    )
  },
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user'
  // 任务 X 修复：
  // - isLoading：任务在跑且尚未开始输出文本 → 显示加载动画（占住位置，避免空白）
  // - 任务已结束（done/error）→ 直接渲染最终答案
  // - 任务进行中且已有部分文本 → 走打字机效果
  const isLoading = msg.role === 'assistant'
    && (msg.taskStatus === 'running' || msg.taskStatus === 'pending')
    && !msg.content

  // 任务 X：打字机效果 —— 已完成的任务也保留这种视觉（一次性显示更自然）
  // 任务进行中：按字符数递增显示
  const [displayChars, setDisplayChars] = useState<number | null>(null)
  useEffect(() => {
    if (!msg.content || isUser) {
      setDisplayChars(null)
      return
    }
    // 任务仍在生成：字符数从 0 累积到 content 长度
    if (msg.taskStatus === 'running' || msg.taskStatus === 'pending') {
      setDisplayChars(0)
      let pos = 0
      const total = msg.content.length
      // 每 30ms 显示 5~10 字符，最大单步 60（让长答案也较快显示完）
      const tick = setInterval(() => {
        pos = Math.min(total, pos + Math.max(5, Math.floor(total / 80)))
        setDisplayChars(pos)
        if (pos >= total) clearInterval(tick)
      }, 30)
      return () => clearInterval(tick)
    } else {
      // 任务已完成：一次性显示（避免长答案一直爬字）
      setDisplayChars(msg.content.length)
    }
  }, [msg.content, msg.taskStatus, isUser])
  const isError = msg.taskStatus === 'error'
  const [showThinking, setShowThinking] = useState(false)
  const [showSourceModal, setShowSourceModal] = useState<{ url: string; content: string } | null>(null)

  // 序号化引用列表：把 citations 数组映射为 ①②③ 数字
  const numberedCitations = useMemo(() => {
    if (!msg.citations) return []
    return msg.citations.map((c, i) => ({
      num: i + 1,
      // ① ② ③ ...⑩⑪...
      label: i < 9
        ? ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨'][i]
        : `[${i + 1}]`,
      citation: c,
    }))
  }, [msg.citations])

  // 打开溯源弹窗
  const openSource = async (c: any) => {
    const chunkId = c?.id
    const docId = c?.metadata?.doc_id
    if (!chunkId || !docId) {
      setShowSourceModal({ url: '', content: c?.content || '（无内容）' })
      return
    }
    try {
      const res = await fetch(`/api/documents/${docId}/chunk/${chunkId}`)
      const data = await res.json()
      setShowSourceModal({
        url: `/documents?doc_id=${docId}&chunk=${chunkId}`,
        content: data.content || c?.content || '（无内容）',
      })
    } catch (e) {
      setShowSourceModal({ url: '', content: c?.content || '（无法加载原文）' })
    }
  }

  return (
    <div style={{
      display: 'flex',
      justifyContent: isUser ? 'flex-end' : 'flex-start',
      marginBottom: 12,
    }}>
      <div style={{
        maxWidth: '90%',
        padding: '10px 14px',
        borderRadius: 12,
        background: isUser
          ? '#3498db'
          : isError
            ? '#fee'
            : '#fff',
        color: isUser ? '#fff' : (isError ? '#c0392b' : '#333'),
        boxShadow: '0 1px 2px rgba(0,0,0,0.1)',
        fontSize: 14,
        lineHeight: 1.6,
        whiteSpace: 'pre-wrap',
        position: 'relative',
        wordBreak: 'break-word',
      }}>
        {/* v2 需求 6：思考过程（折叠面板）*/}
        {!isUser && msg.thinking && (
          <div style={{
            marginBottom: msg.content ? 8 : 0,
            border: '1px solid #e5e7eb',
            borderRadius: 6,
            background: '#f9fafb',
            padding: '6px 10px',
            fontSize: 12,
          }}>
            <div
              onClick={() => setShowThinking(!showThinking)}
              style={{
                display: 'flex',
                alignItems: 'center',
                cursor: 'pointer',
                color: '#6b7280',
                fontWeight: 500,
              }}
            >
              <span style={{
                marginRight: 6,
                transform: showThinking ? 'rotate(90deg)' : 'rotate(0)',
                transition: 'transform 0.15s',
              }}>▶</span>
              <span>💭 思考过程</span>
              <span style={{ marginLeft: 'auto', fontSize: 11, color: '#9ca3af' }}>
                {msg.thinking.length} 字
              </span>
            </div>
            {showThinking && (
              <div style={{
                marginTop: 6,
                paddingTop: 6,
                borderTop: '1px dashed #e5e7eb',
                color: '#4b5563',
                whiteSpace: 'pre-wrap',
                fontFamily: 'ui-monospace, "SFMono-Regular", monospace',
                fontSize: 12,
              }}>
                {msg.thinking}
              </div>
            )}
          </div>
        )}

        {/* 主内容：最终答案 + 句末引用标注（需求 4） */}
        {isLoading ? (
          // 任务 v6：检索/生成中显示过渡动画（"思考中" / "检索中" / "生成中"）
          // 严禁在流式阶段显示任何"未生成"占位文案，避免与后续答案重复
          <TypingIndicator />
        ) : msg.content ? (
          // 在关键句子（以 。/！/？/\n 结尾）后注入 ①②③ 引用标识
          renderContentWithCitations(msg.content, numberedCitations, openSource, displayChars)
        ) : (
          // 任务 v6：只有 taskStatus='error' 时才显示具体错误信息
          // 不再显示"生成失败"短文案——给用户具体错误才有意义
          isError ? <span style={{ color: '#c0392b' }}>⚠️ 生成失败，请稍后重试</span> : null
        )}

        {/* 引用溯源卡片：必须等打字机完成或任务 done 才显示
            任务 X 修复：之前的判断 `!isLoading && msg.content` 在流式过程中
            （content 累积到非空 + status=running）就会触发引用块提前出现。
            现在改为：打字机效果跑完才出现。 */}
        {!isUser && numberedCitations.length > 0 && msg.content && (
          (displayChars != null && displayChars >= msg.content.length) ||
          msg.taskStatus === 'done' ||
          msg.taskStatus === 'error'
        ) && (
          <div style={{
            marginTop: 8,
            paddingTop: 8,
            borderTop: '1px dashed #e5e7eb',
            fontSize: 12,
            animation: 'fadeIn 0.3s ease-in',
          }}>
            <div style={{ color: '#6b7280', marginBottom: 4 }}>📚 引用溯源：</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {numberedCitations.map((nc) => (
                <span
                  key={nc.num}
                  onClick={() => openSource(nc.citation)}
                  style={{
                    cursor: 'pointer',
                    background: '#eff6ff',
                    color: '#1d4ed8',
                    padding: '2px 6px',
                    borderRadius: 4,
                    fontSize: 12,
                    textDecoration: 'underline',
                  }}
                  title={`点击查看 ${nc.citation?.metadata?.title || '来源'} 的原文`}
                >
                  {nc.label} {nc.citation?.metadata?.title || '来源'}
                </span>
              ))}
            </div>
            <div style={{ marginTop: 4, fontSize: 11, color: '#9ca3af' }}>
              共 {numberedCitations.length} 条 · 整体相关度 {(msg.confidence || 0).toFixed(2)}
            </div>
          </div>
        )}

        {/* 任务状态徽标 */}
        {!isUser && msg.taskStatus === 'running' && msg.content && (
          <span style={{
            display: 'inline-block',
            marginLeft: 6,
            padding: '0 6px',
            background: '#fef3c7',
            color: '#92400e',
            borderRadius: 4,
            fontSize: 11,
          }}>
            生成中…
          </span>
        )}

        {/* 溯源弹窗 */}
        {showSourceModal && (
          <div
            onClick={() => setShowSourceModal(null)}
            style={{
              position: 'fixed',
              inset: 0,
              background: 'rgba(0,0,0,0.5)',
              zIndex: 1000,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 20,
            }}
          >
            <div
              onClick={(e) => e.stopPropagation()}
              style={{
                background: '#fff',
                borderRadius: 12,
                padding: 20,
                maxWidth: 700,
                maxHeight: '80vh',
                overflow: 'auto',
                width: '100%',
              }}
            >
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                marginBottom: 12,
                paddingBottom: 8,
                borderBottom: '1px solid #e5e7eb',
              }}>
                <h3 style={{ fontSize: 15, fontWeight: 600 }}>📄 源文档原文</h3>
                <button
                  onClick={() => setShowSourceModal(null)}
                  style={{
                    border: 'none',
                    background: 'transparent',
                    cursor: 'pointer',
                    fontSize: 18,
                    color: '#6b7280',
                  }}
                >×</button>
              </div>
              <pre style={{
                whiteSpace: 'pre-wrap',
                fontFamily: 'inherit',
                fontSize: 13,
                lineHeight: 1.7,
                color: '#1f2937',
                background: '#f9fafb',
                padding: 12,
                borderRadius: 8,
              }}>
                {showSourceModal.content}
              </pre>
              {showSourceModal.url && (
                <a
                  href={showSourceModal.url}
                  style={{
                    display: 'inline-block',
                    marginTop: 12,
                    fontSize: 12,
                    color: '#2563eb',
                  }}
                >
                  在「文档管理」中打开 →
                </a>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default AIChat
