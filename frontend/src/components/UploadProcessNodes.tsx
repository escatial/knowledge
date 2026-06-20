/**
 * UploadProcessNodes - 文档上传全生命周期节点可视化
 *
 * 9 大关键节点（按时间顺序）：
 *  1. 文件整体上传启动     → onUploadProgress 0% 触发
 *  2. 分块上传校验         → onUploadProgress 100% 后等后端响应
 *  3. 分块并行上传         → status="正在解析文档..." progress=5
 *  4. 分块合并完成         → status 跳到分块策略阶段 progress=20
 *  5. 文本提取完成         → status 跳到保存文档 progress=60
 *  6. 图谱生成启动         → status="正在构建向量索引..." progress=60
 *  7. 图谱节点识别         → progress 60→80
 *  8. 图谱关系构建         → progress 80→100
 *  9. 图谱完整生成         → done=true & progress=100
 *
 * 设计要点：
 *  - 水平流式布局（md 以上）| 小屏自动转纵向
 *  - 状态机：pending | in_progress | done | error
 *  - in_progress 脉冲动画（ring + animate-pulse）
 *  - error 状态显示错误详情 + 重试按钮
 *  - 节点间连线随状态变色
 *  - 自定义数据属性 data-status / data-stage 便于 e2e 测试
 */
import { useEffect, useState } from 'react'
import {
  Check, Loader2, AlertCircle, RefreshCw,
  Upload, ShieldCheck, Split, Combine, FileSearch,
  Brain, Network, GitBranch, Sparkles,
} from 'lucide-react'

export type NodeStatus = 'pending' | 'in_progress' | 'done' | 'error'

export interface ProcessNode {
  id: string
  label: string
  description: string
  icon: React.ComponentType<{ className?: string }>
  status: NodeStatus
  errorMessage?: string
  /** 用于 e2e 标识 */
  stage: number
}

// 9 节点配置（顺序固定）
export const STAGES: Array<{
  id: string
  label: string
  description: string
  icon: React.ComponentType<{ className?: string }>
  stage: number
}> = [
  { id: 'upload_start', label: '文件上传', description: '整体上传启动', icon: Upload, stage: 1 },
  { id: 'chunk_validate', label: '分块校验', description: '校验文件可分块性', icon: ShieldCheck, stage: 2 },
  { id: 'chunk_upload', label: '分块上传', description: '分块并行上传', icon: Split, stage: 3 },
  { id: 'chunk_merge', label: '分块合并', description: '合并为完整文本', icon: Combine, stage: 4 },
  { id: 'text_extract', label: '文本提取', description: '提取结构化文本', icon: FileSearch, stage: 5 },
  { id: 'graph_start', label: '图谱启动', description: '准备图谱生成', icon: Brain, stage: 6 },
  { id: 'graph_node', label: '节点识别', description: '识别实体节点', icon: Network, stage: 7 },
  { id: 'graph_relation', label: '关系构建', description: '构建节点关系', icon: GitBranch, stage: 8 },
  { id: 'graph_done', label: '图谱完成', description: '图谱入库完成', icon: Sparkles, stage: 9 },
]

/**
 * 根据后端 progress + status 推断当前节点状态
 */
export function deriveNodeStates(
  progress: number,
  status: string,
  error: string | undefined,
): NodeStatus[] {
  if (error) {
    // 错误时：从 error 之前最近的 done 状态截断
    const errIdx = findErrorStage(progress, status)
    const arr: NodeStatus[] = STAGES.map(() => 'pending')
    for (let i = 0; i < errIdx; i++) arr[i] = 'done'
    arr[errIdx] = 'error'
    return arr
  }
  const arr: NodeStatus[] = STAGES.map(() => 'pending')
  for (let i = 0; i < STAGES.length; i++) {
    if (i < progressToStage(progress)) arr[i] = 'done'
    else if (i === progressToStage(progress)) arr[i] = 'in_progress'
    else arr[i] = 'pending'
  }
  return arr
}

function progressToStage(p: number): number {
  // 0-5: stage 0 in_progress (upload_start)
  // 5: stage 1 in_progress (chunk_validate)
  // 5-10: stage 2 in_progress (chunk_upload)
  // 10-20: stage 3 in_progress (chunk_merge)
  // 20-50: stage 4 in_progress (text_extract) 实际是分块进行
  // 50-60: stage 4 in_progress 仍是 text_extract
  // 60-80: stage 5 in_progress (graph_start)
  // 60-80: stage 6 in_progress (graph_node)
  // 80-100: stage 7 in_progress (graph_relation)
  // 100: stage 8 done (graph_done)
  if (p <= 0) return 0
  if (p < 5) return 0
  if (p < 10) return 1
  if (p < 20) return 2
  if (p < 50) return 3
  if (p < 60) return 4
  if (p < 80) return 5   // 60-80 在 graph_start 范围（也是图谱节点识别）
  if (p < 100) return 7  // 80-100 在 graph_relation 范围
  return 8
}

function findErrorStage(progress: number, status: string): number {
  // 状态文案包含"分块"则错误在分块阶段
  if (status.includes('分块')) return Math.max(2, progressToStage(progress))
  if (status.includes('解析')) return Math.max(1, progressToStage(progress))
  if (status.includes('保存') || status.includes('向量')) return Math.max(5, progressToStage(progress))
  if (status.includes('图谱')) return Math.max(6, progressToStage(progress))
  return Math.max(0, progressToStage(progress))
}

interface UploadProcessNodesProps {
  progress: number
  status: string
  error?: string
  done?: boolean
  onRetry?: () => void
  /** 仅在上传中显示；true 时无文件或 done 后隐藏 */
  visible: boolean
}

export default function UploadProcessNodes({
  progress, status, error, done, onRetry, visible,
}: UploadProcessNodesProps) {
  // 状态数组
  const [statuses, setStatuses] = useState<NodeStatus[]>(
    STAGES.map(() => 'pending')
  )
  // 用于平滑动画：先标记 in_progress，500ms 后标记 done
  const [transitionalStage, setTransitionalStage] = useState<number | null>(null)

  useEffect(() => {
    if (!visible) {
      setStatuses(STAGES.map(() => 'pending'))
      setTransitionalStage(null)
      return
    }
    const next = deriveNodeStates(progress, status, error)
    // 平滑过渡：先 in_progress 闪一下再 done
    const cur = progressToStage(progress)
    if (cur > 0) setTransitionalStage(cur)
    setStatuses(next)
    const t = setTimeout(() => {
      // 当 done 时，把所有 stage 都标记 done（除了 error 那个）
      if (done) {
        setStatuses(STAGES.map((_, i) => next[i] === 'error' ? 'error' : 'done'))
        setTransitionalStage(null)
      } else {
        setTransitionalStage(null)
      }
    }, 400)
    return () => clearTimeout(t)
  }, [progress, status, error, done, visible])

  if (!visible) return null

  const errorIdx = statuses.findIndex((s) => s === 'error')

  return (
    <div
      data-testid="upload-process-nodes"
      className="mt-3 p-3 rounded-xl bg-gradient-to-br from-slate-50 to-white border border-slate-100"
    >
      {/* 头部状态文案 */}
      <div className="flex items-center gap-2 mb-2 text-[11px]">
        {done ? (
          <span className="flex items-center gap-1 text-emerald-600 font-medium">
            <Check className="h-3 w-3" /> 上传完成
          </span>
        ) : error ? (
          <span className="flex items-center gap-1 text-red-500 font-medium">
            <AlertCircle className="h-3 w-3" /> 上传失败：{error}
          </span>
        ) : (
          <span className="flex items-center gap-1 text-slate-500">
            <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
            {status || '准备中...'}
            <span className="text-slate-400">· {progress}%</span>
          </span>
        )}
      </div>

      {/* 节点列表：水平流式 / 纵向自适应 */}
      <ol
        data-testid="process-nodes"
        className="flex flex-col md:flex-row md:items-stretch gap-2 md:gap-0"
      >
        {STAGES.map((stage, i) => {
          const s = statuses[i] ?? 'pending'
          const Icon = stage.icon
          const isLast = i === STAGES.length - 1
          return (
            <li
              key={stage.id}
              data-stage={stage.stage}
              data-status={s}
              data-testid={`node-${stage.id}`}
              className="flex md:flex-1 md:items-stretch relative"
            >
              <NodeItem
                stage={stage}
                status={s}
                Icon={Icon}
                isError={errorIdx === i}
                errorMessage={s === 'error' ? error : undefined}
                onRetry={onRetry}
              />
              {/* 连接线（最后一个节点不需要） */}
              {!isLast && (
                <div
                  aria-hidden
                  data-testid={`connector-${i}`}
                  className={`
                    ${connectorOrientation}
                    ${connectorColor(s, statuses[i + 1])}
                  `}
                />
              )}
            </li>
          )
        })}
      </ol>

      {/* 错误详情区（error 节点下方） */}
      {error && errorIdx >= 0 && (
        <div
          data-testid="error-detail"
          className="mt-2 p-2 rounded-lg bg-red-50 border border-red-100 text-[11px] text-red-600 flex items-start gap-2"
        >
          <AlertCircle className="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="font-medium">
              「{STAGES[errorIdx]?.label}」阶段失败
            </div>
            <div className="opacity-80 break-words">{error}</div>
          </div>
          {onRetry && (
            <button
              onClick={onRetry}
              data-testid="node-retry"
              className="flex-shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-md bg-white border border-red-200 text-red-600 hover:bg-red-100 transition-colors"
            >
              <RefreshCw className="h-3 w-3" />
              重试
            </button>
          )}
        </div>
      )}
    </div>
  )
}

const connectorOrientation = `
  md:flex-1 md:h-0.5 md:mx-1 md:self-center md:min-w-[8px]
  h-0.5 w-6 ml-3 my-0.5 self-start md:self-center
`

function connectorColor(curr: NodeStatus, next: NodeStatus): string {
  // 当前已完成且下一个 in_progress/done：已连线
  if (curr === 'done') return 'bg-emerald-300'
  if (curr === 'in_progress') return 'bg-blue-300 animate-pulse'
  if (curr === 'error') return 'bg-red-300'
  return 'bg-slate-200'
}

function NodeItem({
  stage, status, Icon, isError, errorMessage, onRetry,
}: {
  stage: typeof STAGES[number]
  status: NodeStatus
  Icon: React.ComponentType<{ className?: string }>
  isError: boolean
  errorMessage?: string
  onRetry?: () => void
}) {
  // 颜色与样式：与现有 OS 风格保持一致（白底 + 蓝/绿/红/灰）
  const styles: Record<NodeStatus, { dot: string; icon: string; text: string; ring: string }> = {
    pending: {
      dot: 'bg-slate-200 text-slate-400',
      icon: 'text-slate-400',
      text: 'text-slate-500',
      ring: '',
    },
    in_progress: {
      dot: 'bg-blue-500 text-white',
      icon: 'text-white',
      text: 'text-blue-700',
      ring: 'ring-2 ring-blue-200 animate-pulse',
    },
    done: {
      dot: 'bg-emerald-500 text-white',
      icon: 'text-white',
      text: 'text-emerald-700',
      ring: '',
    },
    error: {
      dot: 'bg-red-500 text-white',
      icon: 'text-white',
      text: 'text-red-600',
      ring: 'ring-2 ring-red-200',
    },
  }
  const s = styles[status]
  return (
    <div
      className={`
        relative flex md:flex-col items-center gap-2 md:gap-1
        px-2 py-1.5 md:px-1 md:py-1
        rounded-lg
        ${status === 'in_progress' ? 'bg-blue-50/60' : ''}
        ${status === 'error' ? 'bg-red-50/60' : ''}
        ${status === 'done' ? 'bg-emerald-50/40' : ''}
      `}
      title={errorMessage || stage.description}
    >
      {/* 圆点（包含图标） */}
      <div
        className={`
          flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center
          ${s.dot} ${s.ring}
        `}
      >
        {status === 'in_progress' ? (
          <Loader2 className={`h-3.5 w-3.5 animate-spin ${s.icon}`} />
        ) : status === 'done' ? (
          <Check className={`h-3.5 w-3.5 ${s.icon}`} />
        ) : status === 'error' ? (
          <AlertCircle className={`h-3.5 w-3.5 ${s.icon}`} />
        ) : (
          <Icon className={`h-3.5 w-3.5 ${s.icon}`} />
        )}
      </div>
      {/* 文字（横向时压缩，纵向时显示） */}
      <div className="flex flex-col md:items-center min-w-0">
        <span className={`text-[10px] font-medium ${s.text} truncate`}>
          {stage.label}
        </span>
        <span className="hidden md:block text-[9px] text-slate-400 truncate max-w-[80px]">
          {stage.description}
        </span>
      </div>
      {/* error 时在节点上叠加重试入口（除了下方已显示的） */}
      {isError && onRetry && (
        <button
          onClick={onRetry}
          className="ml-auto md:ml-0 md:mt-1 inline-flex items-center gap-0.5 text-[9px] text-red-600 hover:text-red-800 transition-colors"
          title="重试"
          data-testid="node-retry-inline"
        >
          <RefreshCw className="h-2.5 w-2.5" />
          重试
        </button>
      )}
    </div>
  )
}
