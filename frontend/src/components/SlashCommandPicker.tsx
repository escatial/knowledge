/**
 * 任务 1.3：聊天框快捷指令选择器
 *
 * - 上下键导航（ArrowUp/ArrowDown）
 * - 回车选中
 * - Esc 关闭
 * - 鼠标悬停高亮同步键盘选中
 */
import { useEffect, useRef } from 'react'
import { ChevronRight } from 'lucide-react'
import type { SlashCommand } from '../data/slashCommands'

interface Props {
    commands: SlashCommand[]
    selectedIndex: number
    onSelect: (cmd: SlashCommand) => void
    onHover: (index: number) => void
    keyword: string
    position?: { top: number; left: number; width: number }
}

const CATEGORY_LABELS: Record<string, string> = {
    navigation: '导航',
    action: '操作',
    utility: '工具',
    kb: '知识库'
}

export default function SlashCommandPicker({
    commands,
    selectedIndex,
    onSelect,
    onHover,
    keyword
}: Props) {
    const listRef = useRef<HTMLDivElement>(null)

    // 滚动到选中项
    useEffect(() => {
        const el = listRef.current?.querySelector(`[data-idx="${selectedIndex}"]`)
        if (el && listRef.current) {
            el.scrollIntoView({ block: 'nearest' })
        }
    }, [selectedIndex])

    if (commands.length === 0) {
        return (
            <div className="absolute z-50 left-0 right-0 bottom-full mb-2 bg-white rounded-xl shadow-2xl border border-gray-200 p-4">
                <p className="text-sm text-gray-500 text-center">
                    没有匹配的指令「<span className="font-mono text-red-500">/{keyword}</span>」
                </p>
                <p className="text-xs text-gray-400 text-center mt-1">试试 /help 查看所有指令</p>
            </div>
        )
    }

    return (
        <div
            ref={listRef}
            className="absolute z-50 left-0 right-0 bottom-full mb-2 bg-white rounded-xl shadow-2xl border border-gray-200 overflow-hidden max-h-80 overflow-y-auto"
        >
            <div className="px-3 py-2 border-b border-gray-100 flex items-center justify-between bg-gradient-to-r from-blue-50 to-indigo-50">
                <span className="text-xs font-semibold text-gray-600">
                    ⚡ 快捷指令 <span className="text-gray-400 ml-1">↑↓ 选择 Enter 确认 Esc 关闭</span>
                </span>
                <span className="text-[10px] text-gray-400">共 {commands.length} 条</span>
            </div>

            {Object.entries(
                commands.reduce<Record<string, SlashCommand[]>>((acc, cmd) => {
                    const k = cmd.category
                    if (!acc[k]) acc[k] = []
                    acc[k].push(cmd)
                    return acc
                }, {})
            ).map(([cat, items]) => (
                <div key={cat}>
                    <div className="px-3 py-1 text-[10px] font-bold text-gray-400 uppercase tracking-wider bg-gray-50/50">
                        {CATEGORY_LABELS[cat] || cat}
                    </div>
                    {items.map(cmd => {
                        const idx = commands.indexOf(cmd)
                        const isSelected = idx === selectedIndex
                        return (
                            <button
                                key={cmd.cmd}
                                data-idx={idx}
                                onClick={() => onSelect(cmd)}
                                onMouseEnter={() => onHover(idx)}
                                className={`
                                    w-full flex items-center gap-3 px-3 py-2.5 text-left text-sm transition-colors
                                    ${isSelected ? 'bg-blue-50 text-blue-900' : 'hover:bg-gray-50 text-gray-700'}
                                `}
                            >
                                <span className="text-lg shrink-0 w-7 text-center">{cmd.icon}</span>
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-1.5">
                                        <span className={`font-semibold ${isSelected ? 'text-blue-700' : 'text-gray-900'}`}>
                                            /{cmd.cmd}
                                        </span>
                                        {cmd.aliases && cmd.aliases.length > 0 && (
                                            <span className="text-[10px] text-gray-400 font-mono">
                                                ({cmd.aliases.map(a => `/${a}`).join(' · ')})
                                            </span>
                                        )}
                                        <span className="text-xs text-gray-500 ml-1">· {cmd.label}</span>
                                    </div>
                                    <p className="text-[11px] text-gray-500 mt-0.5 truncate">{cmd.description}</p>
                                </div>
                                {isSelected && (
                                    <ChevronRight className="h-4 w-4 text-blue-500 shrink-0" />
                                )}
                            </button>
                        )
                    })}
                </div>
            ))}
        </div>
    )
}
