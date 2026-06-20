/**
 * 富内容渲染器（v2 - 任务 1+2）
 *
 * 三大模块独立渲染：
 * 1. ThinkingModule  - 思考过程：浅灰斜体 + 可折叠面板
 * 2. AnswerModule    - 正式回答：基础可读字体 + markdown
 * 3. CitationModule  - 引用来源：独立卡片列表
 *
 * 差异化格式：
 * - 正文   : 基础字体 + 段落
 * - 代码   : 暗色背景 + 行号 + 一键复制
 * - 文件名 : 标签样式 + 文件图标
 * - 思考   : 斜体浅灰 + 折叠面板
 */
import { useMemo, useState, useRef, useCallback, isValidElement } from 'react'
import {
  BarChart3, Link2, AlertCircle, ChevronDown, ChevronRight,
  Copy, Check, FileText, FileCode, FileJson, FileType,
  Brain, Sparkles, Quote
} from 'lucide-react'

// =============================================================
// 1. 文件名渲染（任务 2）
// =============================================================
function FileTag({ name }: { name: string }) {
  const ext = name.split('.').pop()?.toLowerCase() || ''
  const Icon =
    ext === 'py' || ext === 'js' || ext === 'ts' || ext === 'java' ? FileCode :
    ext === 'json' ? FileJson :
    ext === 'md' || ext === 'txt' ? FileType :
    FileText
  const color =
    ext === 'py' ? 'bg-blue-50 text-blue-700 border-blue-200' :
    ext === 'js' || ext === 'ts' ? 'bg-amber-50 text-amber-700 border-amber-200' :
    ext === 'json' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' :
    ext === 'pdf' ? 'bg-rose-50 text-rose-700 border-rose-200' :
    'bg-gray-50 text-gray-700 border-gray-200'
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 mx-0.5 rounded-md border text-[12px] font-mono font-medium ${color}`}>
      <Icon className="h-3 w-3" />
      {name}
    </span>
  )
}

// 任务 W：放宽文件名识别（兼容无扩展名但像文件名的字符串）
// 匹配模式：
//  1) name + .ext（标准文件名）
//  2) 数字 + 1+英文 + ≥2 字符中文（无扩展名，如 "01Agent理论基础"）
//  3) 1+大写英文 + 3+字符中文（无扩展名，如 "RAG技术详解"）— 必须前面是行首/列表标记/标点
//  4) 1+大写英文 + ≤2 字符中文也匹配，但**必须**前面是列表标记（避免误判"面向Agent的..."）
function processTextWithFiles(text: string): React.ReactNode {
  // 用捕获组（不是非捕获组），保持 match[1] 语义
  const fileRegex = /([\w\-一-龥]+\.(?:pdf|docx?|txt|md|json|py|js|ts|tsx|jsx|cpp|java|go|rs|html|css|xml|yaml|yml|csv|xlsx?|pptx?)|(\d+[A-Za-z]+[一-龥]{2,}[一-龥\w\-]*)|((?:^|[•·\-\s、，：:；;])[A-Z][A-Za-z0-9]{1,5}[一-龥]{3,}[一-龥\w\-]*))/g
  const parts: React.ReactNode[] = []
  let lastIdx = 0
  let match: RegExpExecArray | null
  let key = 0
  while ((match = fileRegex.exec(text)) !== null) {
    if (match.index > lastIdx) {
      parts.push(text.slice(lastIdx, match.index))
    }
    // 三个子组都可能命中，取第一个非空；模式 3 含前置字符，strip
    const raw = match[1] || match[2] || match[3] || ''
    const name = raw.replace(/^[\s•·\-\、，：:；;]+/, '').trim()
    if (name) {
      parts.push(<FileTag key={`f-${key++}`} name={name} />)
    }
    lastIdx = match.index + match[0].length
  }
  if (lastIdx < text.length) parts.push(text.slice(lastIdx))
  return parts
}

// 任务 1.4：把行内文本中的 ①②③ 等圈数字渲染为 sup 上标
// 接受字符串或 ReactNode（递归处理数组情况）
function renderWithSuperscripts(node: React.ReactNode, keyPrefix: string): React.ReactNode {
  if (typeof node === 'string') {
    return renderStringWithSuperscripts(node, keyPrefix)
  }
  if (Array.isArray(node)) {
    return node.map((n, i) => renderWithSuperscripts(n, `${keyPrefix}-${i}`))
  }
  if (isValidElement(node)) {
    // FileTag 等已经渲染好的元素，原样保留
    return node
  }
  return node
}

// 任务 X：把行内文本中的 `**text**` 渲染为 <strong> 加粗
function renderStringWithBold(text: string, keyPrefix: string): React.ReactNode {
  const re = /\*\*([^*]+)\*\*/g
  const parts: React.ReactNode[] = []
  let lastIdx = 0
  let match: RegExpExecArray | null
  let k = 0
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIdx) {
      parts.push(text.slice(lastIdx, match.index))
    }
    parts.push(
      <strong key={`${keyPrefix}-b-${k++}`} className="font-semibold text-gray-900">
        {match[1]}
      </strong>
    )
    lastIdx = match.index + match[0].length
  }
  if (lastIdx < text.length) parts.push(text.slice(lastIdx))
  return parts.length > 0 ? parts : text
}

// 任务 v6：行内代码 `code` 渲染为 code 样式（暗色背景 + 等宽字体）
// 关键修复：之前没有处理单反引号包裹的代码，导致 LLM 输出的
// `from langchain.tools import tool` 等代码片段显示为普通文字。
// 注意：必须先于加粗/文件名处理（避免 ** 误匹配）
function renderStringWithInlineCode(text: string, keyPrefix: string): React.ReactNode {
  // 匹配单反引号包裹的非空内容（不贪婪、不跨行）
  // 排除三反引号（代码块）开头的情况 —— 已经在 renderInline 处理
  const re = /`([^`\n]+?)`/g
  const parts: React.ReactNode[] = []
  let lastIdx = 0
  let match: RegExpExecArray | null
  let k = 0
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIdx) {
      parts.push(text.slice(lastIdx, match.index))
    }
    parts.push(
      <code
        key={`${keyPrefix}-ic-${k++}`}
        className="px-1.5 py-0.5 mx-0.5 rounded bg-gray-100 text-pink-600 font-mono text-[0.92em] border border-gray-200"
      >
        {match[1]}
      </code>
    )
    lastIdx = match.index + match[0].length
  }
  if (lastIdx < text.length) parts.push(text.slice(lastIdx))
  return parts.length > 0 ? parts : text
}

// 处理内嵌节点中的行内代码（递归）
function processTextWithInlineCode(node: React.ReactNode, keyPrefix: string): React.ReactNode {
  if (typeof node === 'string') {
    return renderStringWithInlineCode(node, keyPrefix)
  }
  if (Array.isArray(node)) {
    return node.map((n, i) => processTextWithInlineCode(n, `${keyPrefix}-${i}`))
  }
  // FileTag / strong / sup 等已经渲染好的元素，原样保留
  return node
}

// 任务 X 升级：先加粗，再上标，再文件名
// 任务 v6：新增行内代码处理（必须先于加粗，避免误匹配）
function processInline(text: string, keyPrefix: string): React.ReactNode {
  let nodes: React.ReactNode = text
  // 第零步：行内代码（最先处理，避免后续规则破坏代码）
  nodes = processTextWithInlineCode(nodes, keyPrefix)
  // 第一步：加粗
  nodes = renderStringWithBold(String(nodes), keyPrefix)
  // 第二步：文件名
  nodes = processTextWithFilesInner(nodes, keyPrefix)
  // 第三步：上标
  nodes = renderWithSuperscripts(nodes, keyPrefix)
  return nodes
}

function processTextWithFilesInner(node: React.ReactNode, keyPrefix: string): React.ReactNode {
  if (typeof node === 'string') {
    return processTextWithFiles(node)
  }
  if (Array.isArray(node)) {
    return node.map((n, i) => processTextWithFilesInner(n, `${keyPrefix}-${i}`))
  }
  return node
}

function renderStringWithSuperscripts(text: string, keyPrefix: string): React.ReactNode {
  // 匹配 ①-⑳ 圈数字（Unicode 0x2460-0x2473）
  const re = /[\u2460-\u2473]/g
  const parts: React.ReactNode[] = []
  let lastIdx = 0
  let match: RegExpExecArray | null
  let k = 0
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIdx) {
      parts.push(text.slice(lastIdx, match.index))
    }
    const label = match[0]
    // 提取编号
    const num = label.codePointAt(0)! - 0x2460 + 1
    parts.push(
      <sup
        key={`${keyPrefix}-sup-${k++}`}
        className="citation-sup inline-flex items-center justify-center min-w-[1.1em] h-[1.1em] mx-0.5 px-1 rounded-full bg-blue-100 text-blue-700 text-[0.65em] font-semibold align-super cursor-pointer hover:bg-blue-200 transition-colors"
        title={`引用 ${num}`}
      >
        {label}
      </sup>
    )
    lastIdx = match.index + 1
  }
  if (lastIdx < text.length) parts.push(text.slice(lastIdx))
  return parts.length > 0 ? parts : text
}

// =============================================================
// 2. 代码块渲染（任务 2：行号+语法高亮+一键复制）
// =============================================================
function detectLang(code: string): string {
  if (/^(import |from |def |class |@|\s*self\.)/m.test(code)) return 'python'
  if (/^(const |let |var |function |=>|import |export )/m.test(code)) return 'javascript'
  if (/^(\s*<\?php|echo |\$\w+\s*=)/m.test(code)) return 'php'
  if (/^#!\s*\/bin\/(ba)?sh/m.test(code)) return 'bash'
  if (/^[{[]/.test(code.trim()) && /[}\]]$/.test(code.trim())) return 'json'
  return 'text'
}

// 极简语法高亮（无需引入 highlight.js 依赖）
function highlight(code: string, lang: string): React.ReactNode[] {
  if (lang === 'text') return [code]
  const lines = code.split('\n')
  return lines.map((line, i) => {
    // 关键字
    let html = line
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
    // 注释
    html = html.replace(/(#.*$|\/\/.*$)/g, '<span style="color:#94a3b8">$1</span>')
    // 字符串
    html = html.replace(/(&quot;[^&]*&quot;|&#039;[^&]*&#039;|&#39;[^&]*&#39;|"[^"]*"|'[^']*'|`[^`]*`)/g,
      '<span style="color:#86efac">$1</span>')
    // 关键字
    const keywords = lang === 'python'
      ? ['def', 'class', 'import', 'from', 'return', 'if', 'else', 'elif', 'for', 'while', 'in', 'is', 'not', 'and', 'or', 'as', 'with', 'try', 'except', 'finally', 'lambda', 'yield', 'global', 'pass', 'break', 'continue']
      : ['const', 'let', 'var', 'function', 'return', 'if', 'else', 'for', 'while', 'in', 'of', 'new', 'class', 'import', 'export', 'from', 'as', 'default', 'async', 'await', 'try', 'catch', 'finally', 'throw']
    const kwRe = new RegExp(`\\b(${keywords.join('|')})\\b`, 'g')
    html = html.replace(kwRe, '<span style="color:#c084fc;font-weight:600">$1</span>')
    // 数字
    html = html.replace(/\b(\d+)\b/g, '<span style="color:#fbbf24">$1</span>')
    return <span key={i} dangerouslySetInnerHTML={{ __html: html + (i < lines.length - 1 ? '\n' : '') }} />
  })
}

function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false)
  const detected = lang || detectLang(code)
  const lines = code.split('\n')
  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }, [code])
  return (
    <div className="my-3 rounded-lg overflow-hidden border border-gray-800 shadow-sm">
      {/* 顶栏 */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-gradient-to-r from-gray-800 to-gray-900 text-gray-300 text-xs">
        <div className="flex items-center gap-2">
          <FileCode className="h-3.5 w-3.5" />
          <span className="font-mono font-semibold">{detected}</span>
          <span className="text-gray-500">· {lines.length} 行</span>
        </div>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 px-2 py-0.5 rounded hover:bg-white/10 transition-colors"
        >
          {copied ? (
            <>
              <Check className="h-3.5 w-3.5 text-green-400" />
              <span className="text-green-400">已复制</span>
            </>
          ) : (
            <>
              <Copy className="h-3.5 w-3.5" />
              <span>复制</span>
            </>
          )}
        </button>
      </div>
      {/* 代码区 */}
      <div className="bg-gray-900 text-gray-100 font-mono text-[13px] leading-relaxed overflow-x-auto">
        <table className="w-full border-collapse">
          <tbody>
            {lines.map((line, idx) => (
              <tr key={idx} className="hover:bg-gray-800/50">
                <td className="select-none text-right pr-3 pl-3 text-gray-500 w-12 border-r border-gray-800 align-top">
                  {idx + 1}
                </td>
                <td className="pl-3 pr-4 align-top whitespace-pre">
                  {highlight(line, detected)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// =============================================================
// 3. 思考过程渲染（任务 1+2：浅灰斜体+折叠面板）
// =============================================================
function ThinkingModule({ content, defaultOpen = true }: { content: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="my-3 rounded-lg border border-gray-200 bg-gradient-to-br from-gray-50 to-slate-50 overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-100/50 transition-colors"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5 text-gray-400" /> : <ChevronRight className="h-3.5 w-3.5 text-gray-400" />}
        <Brain className="h-3.5 w-3.5 text-gray-400" />
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">思考过程</span>
        <span className="text-[10px] text-gray-400 ml-auto">{content.length} 字</span>
      </button>
      {open && (
        <div className="px-4 py-3 border-t border-gray-200/60">
          <p className="text-[13px] italic text-gray-500 leading-relaxed whitespace-pre-wrap font-light">
            {content}
          </p>
        </div>
      )}
    </div>
  )
}

// =============================================================
// 4. 正式回答渲染（任务 1+2：基础字体+markdown+代码块+文件名）
// =============================================================
function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  // 先处理代码块 ```...```
  // 任务 X：放宽匹配 —— 允许语言标识符后没有换行（LLM 偶尔输出 ```python def func()...``` 形式）
  // 仍然要求以 ``` 严格闭合，避免与行内 `code` 冲突
  const codeBlockRe = /```(\w*)[ \t]*\n?([\s\S]*?)```/g
  const parts: React.ReactNode[] = []
  let lastIdx = 0
  let match: RegExpExecArray | null
  let kIdx = 0
  while ((match = codeBlockRe.exec(text)) !== null) {
    if (match.index > lastIdx) {
      parts.push(renderNonCodeText(text.slice(lastIdx, match.index), `${keyPrefix}-nc-${kIdx++}`))
    }
    parts.push(<CodeBlock key={`${keyPrefix}-cb-${kIdx++}`} code={match[2]} lang={match[1]} />)
    lastIdx = match.index + match[0].length
  }
  if (lastIdx < text.length) {
    parts.push(renderNonCodeText(text.slice(lastIdx), `${keyPrefix}-nc-${kIdx++}`))
  }
  return parts
}

// 任务 P3-7：识别 Markdown 表格行（表头 + 分隔行 + 数据行）
// 返回 { header, rows, endIdx }，没有命中返回 null
function parseTableRow(line: string): string[] | null {
  const trimmed = line.trim()
  if (!trimmed.startsWith('|') || !trimmed.endsWith('|')) return null
  // 拆分：去掉首尾的 | 后用 | 切
  const inner = trimmed.slice(1, -1)
  const cells = inner.split('|').map(c => c.trim())
  // 至少 2 列
  if (cells.length < 2) return null
  return cells
}

function isTableSeparator(cells: string[]): boolean {
  // 形如 --- | :---: | :--- | ---:
  return cells.every(c => /^:?-+:?$/.test(c.replace(/\s/g, '')))
}

function renderNonCodeText(text: string, keyPrefix: string): React.ReactNode {
  const lines = text.split('\n')

  // 任务 P3-7：先把连续的表格行聚成一个块
  type Block =
    | { type: 'table'; header: string[]; rows: string[][]; }
    | { type: 'text'; lines: { line: string; idx: number }[] }
  const blocks: Block[] = []
  let i = 0
  while (i < lines.length) {
    const headCells = parseTableRow(lines[i])
    const sepCells = (i + 1 < lines.length) ? parseTableRow(lines[i + 1]) : null
    if (headCells && sepCells && isTableSeparator(sepCells)) {
      // 收集数据行
      const rows: string[][] = []
      let j = i + 2
      while (j < lines.length) {
        const row = parseTableRow(lines[j])
        if (!row) break
        // 长度不匹配时用空字符串补齐
        const padded = Array.from({ length: headCells.length }, (_, k) => row[k] ?? '')
        rows.push(padded)
        j++
      }
      blocks.push({ type: 'table', header: headCells, rows })
      i = j
    } else {
      // 普通文本块：收集连续的"非表格起始"行
      const txt: { line: string; idx: number }[] = []
      while (i < lines.length) {
        const headNow = parseTableRow(lines[i])
        const sepNow = (i + 1 < lines.length) ? parseTableRow(lines[i + 1]) : null
        if (headNow && sepNow && isTableSeparator(sepNow)) break
        txt.push({ line: lines[i], idx: i })
        i++
      }
      blocks.push({ type: 'text', lines: txt })
    }
  }

  return (
    <span key={keyPrefix}>
      {blocks.map((block, blockIdx) => {
        if (block.type === 'table') {
          return (
            <div key={`${keyPrefix}-t-${blockIdx}`} className="my-2 overflow-x-auto">
              <table className="min-w-full border-collapse border border-gray-300 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    {block.header.map((h, k) => (
                      <th key={k} className="border border-gray-300 px-3 py-2 text-left font-semibold text-gray-700">
                        {processInline(h, `${keyPrefix}-th-${blockIdx}-${k}`)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, ri) => (
                    <tr key={ri} className="hover:bg-gray-50">
                      {row.map((cell, ci) => (
                        <td key={ci} className="border border-gray-300 px-3 py-2 text-gray-800">
                          {processInline(cell, `${keyPrefix}-td-${blockIdx}-${ri}-${ci}`)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
        // 普通文本块：按行处理（标题/列表/段落）
        return (
          <span key={`${keyPrefix}-b-${blockIdx}`}>
            {block.lines.map(({ line, idx }) => {
              // 标题
              const h = line.match(/^(#{1,3})\s+(.+)$/)
              if (h) {
                const level = h[1].length
                const sizeClass = level === 1 ? 'text-lg font-bold' : level === 2 ? 'text-base font-bold' : 'text-sm font-semibold'
                return (
                  <div key={idx} className={`${sizeClass} text-gray-800 mt-3 mb-1.5`}>
                    {processInline(h[2], `${keyPrefix}-h-${idx}`)}
                  </div>
                )
              }
              // 列表
              const li = line.match(/^(\s*)[-*]\s+(.+)$/)
              if (li) {
                return (
                  <div key={idx} className="flex gap-2 ml-3 my-0.5 text-gray-700 leading-relaxed">
                    <span className="text-blue-500 shrink-0">•</span>
                    <span>{processInline(li[2], `${keyPrefix}-li-${idx}`)}</span>
                  </div>
                )
              }
              // 空行
              if (line.trim() === '') return <div key={idx} className="h-2" />
              // 普通行
              return (
                <p key={idx} className="text-[14px] text-gray-700 leading-relaxed my-1">
                  {processInline(line, `${keyPrefix}-p-${idx}`)}
                </p>
              )
            })}
          </span>
        )
      })}
    </span>
  )
}

function AnswerModule({ content, streaming, streamingText }: {
  content: string
  streaming?: boolean
  streamingText?: string
}) {
  // 打字机效果：使用 streamingText 替代 content
  const text = streaming ? (streamingText ?? '') : content
  // 拆出 <think>...</think> 块（如有）
  const thinkMatch = text.match(/<think>([\s\S]*?)(?:<\/think>|$)/)
  let thinkText = ''
  let mainText = text
  if (thinkMatch) {
    thinkText = thinkMatch[1]
    mainText = text.replace(thinkMatch[0], '').trim()
  }
  return (
    <div className="space-y-2">
      {thinkText && <ThinkingModule content={thinkText} defaultOpen={!streaming} />}
      <div className="text-gray-700">
        {renderInline(mainText, 'a')}
        {streaming && <span className="inline-block w-[2px] h-[1.1em] ml-0.5 bg-gradient-to-b from-blue-500 to-blue-600 align-middle typing-cursor" style={{ animation: 'cursor-blink 1s steps(1) infinite' }} />}
      </div>
    </div>
  )
}

// =============================================================
// 5. 引用来源渲染（任务 1：独立卡片）
// =============================================================
function CitationModule({ citations }: { citations: any[] }) {
  if (!citations?.length) return null
  return (
    <div className="mt-4 rounded-xl border border-emerald-200/60 bg-gradient-to-br from-emerald-50/40 to-teal-50/30 p-4">
      <div className="flex items-center gap-2 mb-3">
        <Quote className="h-4 w-4 text-emerald-600" />
        <span className="text-xs font-bold text-emerald-700 uppercase tracking-wider">引用来源</span>
        <span className="text-[10px] text-gray-500 ml-auto">{citations.length} 条</span>
      </div>
      <div className="space-y-2">
        {citations.map((cite, idx) => {
          const score = cite.score || 0
          const scoreColor = score > 0.7 ? 'bg-emerald-500' : score > 0.5 ? 'bg-blue-500' : 'bg-amber-500'
          return (
            <div
              key={idx}
              className="flex items-start gap-3 p-2.5 bg-white rounded-lg border border-gray-100 hover:border-emerald-200 hover:shadow-sm transition-all cursor-pointer"
            >
              <div className="w-6 h-6 rounded bg-emerald-100 text-emerald-700 flex items-center justify-center text-xs font-bold shrink-0 mt-0.5">
                {idx + 1}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-gray-800 truncate">
                    {cite.title || cite.doc_title || '文档片段'}
                  </p>
                  {cite.title?.toLowerCase().endsWith('.pdf') && <FileText className="h-3 w-3 text-rose-500 shrink-0" />}
                </div>
                {cite.content && (
                  <p className="text-[12px] text-gray-500 mt-0.5 line-clamp-2 leading-relaxed">
                    {cite.content.slice(0, 150)}{cite.content.length > 150 ? '...' : ''}
                  </p>
                )}
                {score > 0 && (
                  <div className="flex items-center gap-2 mt-1.5">
                    <div className="flex-1 h-1 bg-gray-100 rounded-full overflow-hidden max-w-[120px]">
                      <div className={`h-full ${scoreColor}`} style={{ width: `${score * 100}%` }} />
                    </div>
                    <span className="text-[10px] text-gray-500 font-mono">{(score * 100).toFixed(1)}%</span>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// =============================================================
// 6. 置信度徽章
// =============================================================
function ConfidenceBadge({ confidence, model }: { confidence?: number; model?: string }) {
  if (!confidence) return null
  const color = confidence > 0.8 ? 'bg-emerald-100 text-emerald-700 border-emerald-200' :
                confidence > 0.6 ? 'bg-blue-100 text-blue-700 border-blue-200' :
                'bg-amber-100 text-amber-700 border-amber-200'
  return (
    <div className="flex items-center gap-2 my-2">
      <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold border ${color}`}>
        置信度 {(confidence * 100).toFixed(0)}%
      </span>
      {model && <span className="text-[10px] text-gray-400">模型 {model}</span>}
    </div>
  )
}

// =============================================================
// 7. 主渲染器（任务 1：三大模块独立渲染）
// =============================================================
export type ContentType = 'thinking' | 'text' | 'chart' | 'citation' | 'error' | 'loading'

export interface RichContent {
  type: ContentType
  content: any
  metadata?: {
    confidence?: number
    model?: string
    source?: string
    streaming?: boolean
  }
}

interface RichContentRendererProps {
  contents: RichContent[]
}

export default function RichContentRenderer({ contents }: RichContentRendererProps) {
  // 拆分：思考、回答、引用三大模块
  const { thinkings, answers, citations, others } = useMemo(() => {
    const t: RichContent[] = []
    const a: RichContent[] = []
    const c: RichContent[] = []
    const o: RichContent[] = []
    for (const item of contents) {
      if (item.metadata?.isThinking || item.type === 'thinking') t.push(item)
      else if (item.type === 'citation') c.push(item)
      else if (item.type === 'text') a.push(item)
      else o.push(item)
    }
    return { thinkings: t, answers: a, citations: c, others: o }
  }, [contents])

  return (
    <div className="space-y-3">
      {/* 模块 1：思考过程（独立容器） */}
      {thinkings.length > 0 && (
        <section className="rounded-xl border-l-4 border-gray-300 bg-gray-50/30 p-1">
          {thinkings.map((t, i) => (
            <ThinkingModule key={i} content={String(t.content || '')} defaultOpen={!t.metadata?.streaming} />
          ))}
        </section>
      )}

      {/* 模块 2：正式回答（独立容器） */}
      {answers.length > 0 && (
        <section className="rounded-xl border-l-4 border-blue-400 bg-white p-4">
          <div className="flex items-center gap-2 mb-2">
            <Sparkles className="h-3.5 w-3.5 text-blue-500" />
            <span className="text-xs font-bold text-blue-700 uppercase tracking-wider">正式回答</span>
            {answers[0].metadata?.streaming && (
              <span className="text-[10px] text-blue-500 ml-auto animate-pulse">● 生成中</span>
            )}
          </div>
          {answers.map((a, i) => (
            <div key={i}>
              <AnswerModule
                content={String(a.content || '')}
                streaming={a.metadata?.streaming}
                streamingText={a.metadata?.streaming ? String(a.content || '') : undefined}
              />
              <ConfidenceBadge confidence={a.metadata?.confidence} model={a.metadata?.model} />
            </div>
          ))}
        </section>
      )}

      {/* 模块 3：引用来源（独立容器） */}
      {citations.length > 0 && (
        <section className="rounded-xl border-l-4 border-emerald-400">
          {citations.map((c, i) => (
            <CitationModule key={i} citations={c.content} />
          ))}
        </section>
      )}

      {/* 其他（chart/error/loading） */}
      {others.map((item, idx) => {
        if (item.type === 'chart') {
          return <ChartRenderer key={idx} option={item.content} />
        }
        if (item.type === 'error') {
          return (
            <div key={idx} className="bg-red-50 border border-red-100 rounded-xl p-4 my-3 flex items-start gap-3">
              <AlertCircle className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm text-red-700 font-medium">处理出错</p>
                <p className="text-sm text-red-600 mt-1">{item.content}</p>
              </div>
            </div>
          )
        }
        if (item.type === 'loading') {
          return (
            <div key={idx} className="flex items-center gap-2 text-gray-400 my-2">
              <div className="w-4 h-4 border-2 border-gray-200 border-t-blue-500 rounded-full animate-spin" />
              <span className="text-sm">{item.content || '处理中...'}</span>
            </div>
          )
        }
        return null
      })}
    </div>
  )
}

// 简单柱状图（保留旧功能）
function ChartRenderer({ option }: { option: any }) {
  const chartType = option?.type || 'bar'
  const data = option?.data || []
  const labels = option?.labels || []
  return (
    <div className="bg-white rounded-xl border border-gray-100 p-4 my-3">
      <div className="flex items-center gap-2 mb-3">
        <BarChart3 className="h-4 w-4 text-blue-500" />
        <span className="text-sm font-medium text-gray-700">数据可视化</span>
      </div>
      {chartType === 'bar' && (
        <div className="space-y-2">
          {data.map((value: number, idx: number) => (
            <div key={idx} className="flex items-center gap-3">
              <span className="text-xs text-gray-500 w-16 truncate">{labels[idx] || `项${idx + 1}`}</span>
              <div className="flex-1 bg-gray-100 rounded-full h-6 overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-blue-400 to-blue-600 rounded-full transition-all duration-500"
                  style={{ width: `${Math.min((value / Math.max(...data)) * 100, 100)}%` }}
                />
              </div>
              <span className="text-xs text-gray-600 w-10 text-right">{value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
