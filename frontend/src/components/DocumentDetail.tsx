import { useEffect, useMemo, useState } from 'react'
import { Document } from '../types'
import { Download, ExternalLink, X, FileText, Image as ImageIcon, Code } from 'lucide-react'

interface DocumentDetailProps {
  document: Document
  onClose: () => void
}

// 原始文件直链（后端 /api/documents/{id}/raw）
const rawUrl = (id: string) => `/api/documents/${id}/raw`
// 下载触发（添加 download=1 query 让后端返回 attachment）
const downloadUrl = (id: string) => `/api/documents/${id}/raw?download=1`

// 简易 Markdown 渲染（仅用于 .md 预览）
function renderMarkdownLite(md: string) {
  // 标题
  return md
    .replace(/^### (.*)$/gm, '<h3 style="font-size:15px;margin:12px 0 6px">$1</h3>')
    .replace(/^## (.*)$/gm, '<h2 style="font-size:17px;margin:14px 0 8px">$1</h2>')
    .replace(/^# (.*)$/gm, '<h1 style="font-size:19px;margin:16px 0 8px">$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code style="background:#f1f5f9;padding:1px 4px;border-radius:3px">$1</code>')
    .replace(/\n\n/g, '</p><p style="margin:6px 0">')
    .replace(/\n/g, '<br/>')
}

/**
 * 原始文件预览组件 —— 按 doc.filename / file_type 适配不同预览：
 *  - pdf       → <iframe src=raw>
 *  - 图片       → <img src=raw>
 *  - txt/md/json/csv → fetch raw + 文本/Markdown 渲染
 *  - 其他       → 提示下载（浏览器无法内联预览）
 */
function FilePreview({ document }: { document: Document }) {
  const [textContent, setTextContent] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const filename = document.filename || document.title || ''
  const ext = (filename.split('.').pop() || '').toLowerCase()
  // 同时支持按 Document.file_type 推断
  const fileType = (document.file_type || ext || '').toLowerCase()

  const isPdf = fileType === 'pdf'
  const isImage = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico'].includes(fileType)
  const isText = ['txt', 'md', 'markdown', 'json', 'csv', 'log', 'yaml', 'yml', 'xml', 'html', 'htm', 'css', 'js', 'ts', 'tsx', 'jsx', 'py', 'java', 'go', 'rs', 'c', 'cpp', 'sh'].includes(fileType)

  useEffect(() => {
    if (!isText) return
    setLoading(true)
    setError(null)
    fetch(rawUrl(document.id))
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.text()
      })
      .then((t) => setTextContent(t))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [document.id, isText])

  const html = useMemo(() => {
    if (fileType === 'md' || fileType === 'markdown') {
      return renderMarkdownLite(textContent)
    }
    return null
  }, [textContent, fileType])

  if (isPdf) {
    return (
      <iframe
        src={rawUrl(document.id)}
        title={document.title}
        style={{
          width: '100%',
          height: '60vh',
          border: 'none',
          borderRadius: 8,
          background: '#525659',
        }}
      />
    )
  }

  if (isImage) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', background: '#f1f5f9', borderRadius: 8, padding: 16 }}>
        <img
          src={rawUrl(document.id)}
          alt={document.title}
          style={{ maxWidth: '100%', maxHeight: '60vh', objectFit: 'contain' }}
        />
      </div>
    )
  }

  if (isText) {
    if (loading) return <div style={{ padding: 40, textAlign: 'center', color: '#999' }}>正在加载原始文件...</div>
    if (error) return <div style={{ padding: 20, color: '#dc2626' }}>加载失败：{error}</div>
    return (
      <pre
        style={{
          background: '#f8f9fa',
          borderRadius: 8,
          padding: 16,
          maxHeight: '60vh',
          overflow: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          lineHeight: 1.6,
          fontSize: 13,
          margin: 0,
        }}
        dangerouslySetInnerHTML={html ? { __html: `<div>${html}</div>` } : undefined}
      >
        {html ? undefined : textContent || '(空文件)'}
      </pre>
    )
  }

  // 浏览器无法内联预览的格式：Office、压缩包等
  return (
    <div style={{
      background: '#fef3c7',
      border: '1px solid #fcd34d',
      borderRadius: 8,
      padding: 24,
      textAlign: 'center',
    }}>
      <FileText className="h-10 w-10 mx-auto text-amber-600 mb-2" />
      <p style={{ margin: '4px 0', color: '#92400e' }}>
        {`暂不支持在线预览 .${fileType || '?'} 格式`}
      </p>
      <p style={{ margin: '4px 0', fontSize: 12, color: '#a16207' }}>
        请下载原始文件后用本地应用打开
      </p>
      <a
        href={downloadUrl(document.id)}
        style={{
          display: 'inline-block',
          marginTop: 12,
          padding: '8px 16px',
          background: '#d97706',
          color: '#fff',
          borderRadius: 6,
          textDecoration: 'none',
          fontSize: 14,
        }}
      >
        下载原始文件
      </a>
    </div>
  )
}

function DocumentDetail({ document, onClose }: DocumentDetailProps) {
  const ext = (document.filename || document.title || '').split('.').pop()?.toLowerCase()
  const previewable = ['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'txt', 'md', 'json', 'csv', 'html', 'htm', 'log', 'yaml', 'yml', 'xml'].includes(ext || '')

  return (
    <div
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
      onClick={onClose}
    >
      <div
        style={{
          background: '#fff',
          borderRadius: 12,
          width: '100%',
          maxWidth: 920,
          maxHeight: '90vh',
          overflow: 'auto',
          padding: 24,
          boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, gap: 16 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h2 style={{ margin: 0, fontSize: 20, lineHeight: 1.3, wordBreak: 'break-word' }}>{document.title}</h2>
            <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={{
                display: 'inline-block',
                padding: '4px 12px',
                borderRadius: 20,
                background: '#e3f2fd',
                color: '#1976d2',
                fontSize: 12,
              }}>
                {document.category}
              </span>
              {ext && (
                <span style={{
                  display: 'inline-flex', alignItems: 'center', gap: 4,
                  padding: '4px 10px', borderRadius: 20,
                  background: '#f1f5f9', color: '#475569', fontSize: 12,
                }}>
                  {previewable ? <ImageIcon className="h-3 w-3" /> : <Code className="h-3 w-3" />}
                  .{ext}
                </span>
              )}
              <span style={{ fontSize: 12, color: '#999' }}>
                {new Date(document.created_at).toLocaleString()}
              </span>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
            <a
              href={rawUrl(document.id)}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 4,
                padding: '6px 12px', borderRadius: 6,
                background: '#f1f5f9', color: '#475569',
                textDecoration: 'none', fontSize: 13,
              }}
              title="新窗口打开原始文件"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              新窗口
            </a>
            <a
              href={downloadUrl(document.id)}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 4,
                padding: '6px 12px', borderRadius: 6,
                background: '#1976d2', color: '#fff',
                textDecoration: 'none', fontSize: 13,
              }}
            >
              <Download className="h-3.5 w-3.5" />
              下载
            </a>
            <button
              onClick={onClose}
              style={{
                border: 'none', background: 'transparent',
                fontSize: 22, cursor: 'pointer', color: '#999',
                padding: '0 6px', lineHeight: 1,
              }}
              aria-label="关闭"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* 预览主体 */}
        <FilePreview document={document} />

        {/* 解析后内容（折叠，作为参考） */}
        {document.content && (
          <details style={{ marginTop: 16 }}>
            <summary style={{ cursor: 'pointer', color: '#475569', fontSize: 13, userSelect: 'none' }}>
              查看解析后文本内容（用于检索）
            </summary>
            <pre style={{
              background: '#f8f9fa',
              borderRadius: 8,
              padding: 16,
              marginTop: 8,
              maxHeight: 200,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              lineHeight: 1.5,
              fontSize: 12,
              color: '#64748b',
            }}>
              {document.content}
            </pre>
          </details>
        )}
      </div>
    </div>
  )
}

export default DocumentDetail
