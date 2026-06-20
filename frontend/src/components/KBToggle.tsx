/**
 * 任务 2：KB 选择器开关（用于「系统设置 → 高级」页）
 * - 控制侧边栏 KBSelector 的显示
 * - 持久化到 localStorage
 * - 触发 kb-selector-toggle 事件，Layout 监听后切换显示
 */
import { useState } from 'react'

const STORAGE_KEY = 'kb_selector_visible'

function getInitial(): boolean {
    try {
        return localStorage.getItem(STORAGE_KEY) === 'true'
    } catch {
        return false
    }
}

export default function KBToggle() {
    const [enabled, setEnabled] = useState<boolean>(getInitial())

    const toggle = () => {
        const next = !enabled
        setEnabled(next)
        try {
            localStorage.setItem(STORAGE_KEY, String(next))
        } catch {
            // ignore
        }
        // 广播给 Layout
        window.dispatchEvent(new CustomEvent('kb-selector-toggle', { detail: { visible: next } }))
    }

    return (
        <button
            onClick={toggle}
            className={`
                relative w-12 h-7 rounded-full transition-colors shrink-0
                ${enabled ? 'bg-indigo-500' : 'bg-gray-300'}
            `}
            title={enabled ? '点击关闭' : '点击开启'}
        >
            <span
                className={`
                    absolute top-0.5 left-0.5 w-6 h-6 rounded-full bg-white shadow-sm
                    transition-transform duration-200
                    ${enabled ? 'translate-x-5' : 'translate-x-0'}
                `}
            />
        </button>
    )
}
