/**
 * 任务 1.2：搜索进度条组件
 *
 * 实时显示：
 * - 进度百分比
 * - 当前阶段（向量/图谱/关键词/完成）
 * - 已用时间 / 预计剩余时间
 * - 阶段标签（如"向量检索完成（5 条）"）
 * - 加载动画
 */
import { useEffect, useState } from 'react'
import { Loader2, CheckCircle2, AlertCircle, Activity } from 'lucide-react'

export interface SearchProgress {
    stage: 'init' | 'vector' | 'graph' | 'keyword' | 'finalize' | 'done' | 'error'
    label: string
    percent: number       // 0-100
    elapsed_ms: number
    remaining_ms?: number
    message?: string      // warn/error 时使用
}

interface Props {
    progress: SearchProgress | null
    visible: boolean
    onCancel?: () => void
}

export default function SearchProgress({ progress, visible, onCancel }: Props) {
    if (!visible || !progress) return null

    const isError = progress.stage === 'error'
    const isDone = progress.stage === 'done' || progress.percent >= 100

    // 计算剩余时间（基于已完成进度的速率）
    const remaining = isDone ? 0 : (
        progress.remaining_ms ??
        Math.max(0, Math.round((progress.elapsed_ms / Math.max(progress.percent, 1)) * (100 - progress.percent)))
    )

    return (
        <div className="w-full bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100 rounded-xl p-4 shadow-sm">
            <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                    {isError ? (
                        <AlertCircle className="h-4 w-4 text-red-500" />
                    ) : isDone ? (
                        <CheckCircle2 className="h-4 w-4 text-green-500" />
                    ) : (
                        <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
                    )}
                    <span className={`text-sm font-medium ${
                        isError ? 'text-red-700' : isDone ? 'text-green-700' : 'text-blue-700'
                    }`}>
                        {progress.label}
                    </span>
                </div>
                <div className="flex items-center gap-3 text-xs text-gray-500">
                    <span>
                        <Activity className="h-3 w-3 inline mr-1" />
                        {progress.elapsed_ms}ms
                    </span>
                    {!isDone && (
                        <span>剩余 ~{Math.round(remaining / 100) / 10}s</span>
                    )}
                    <span className="font-mono text-base font-bold text-blue-700">
                        {progress.percent}%
                    </span>
                </div>
            </div>

            <div className="h-2 bg-white rounded-full overflow-hidden border border-blue-100">
                <div
                    className={`h-full transition-all duration-300 ease-out ${
                        isError
                            ? 'bg-gradient-to-r from-red-400 to-red-500'
                            : isDone
                            ? 'bg-gradient-to-r from-green-400 to-emerald-500'
                            : 'bg-gradient-to-r from-blue-400 to-indigo-500'
                    }`}
                    style={{ width: `${progress.percent}%` }}
                />
            </div>

            {/* 阶段指示器 */}
            <div className="mt-3 flex items-center justify-between text-[10px] text-gray-500">
                {['init', 'vector', 'graph', 'keyword', 'done'].map((s, i) => {
                    const stages: any = { init: '初始化', vector: '向量', graph: '图谱', keyword: '关键词', done: '完成' }
                    const order = ['init', 'vector', 'graph', 'keyword', 'done']
                    const currentIdx = order.indexOf(progress.stage === 'error' ? 'keyword' : progress.stage)
                    const thisIdx = order.indexOf(s)
                    const reached = thisIdx <= currentIdx || isDone
                    return (
                        <div key={s} className="flex items-center gap-1">
                            <div className={`w-1.5 h-1.5 rounded-full ${
                                reached
                                    ? (isDone ? 'bg-green-500' : 'bg-blue-500')
                                    : 'bg-gray-300'
                            }`} />
                            <span className={reached ? 'text-blue-700 font-medium' : ''}>
                                {stages[s]}
                            </span>
                            {i < 4 && <span className="text-gray-300">—</span>}
                        </div>
                    )
                })}
            </div>

            {onCancel && !isDone && (
                <button
                    onClick={onCancel}
                    className="mt-3 text-xs text-gray-500 hover:text-red-500"
                >
                    取消检索
                </button>
            )}
        </div>
    )
}
