/**
 * 聊天框快捷指令系统
 *
 * 触发：输入框输入 "/" 时弹出列表
 * 导航：上下键切换，回车选中，Esc 关闭
 *
 * 指令动作类型：
 * - "insert-text"  插入提示词到输入框（不直接发送）
 * - "send"         自动发送（用户按回车时直接执行）
 * - "action"       触发自定义回调（由 ChatPage 实现）
 */
export interface SlashCommand {
    cmd: string                  // 指令名（不含 /），如 "search"
    aliases?: string[]           // 别名
    label: string                // 列表中显示的标题
    description: string          // 功能说明
    icon: string                 // emoji 图标（前端会替换为 lucide-react 图标）
    category: 'navigation' | 'action' | 'utility' | 'kb'
    placeholder?: string         // 插入到输入框的提示词（用于 insert-text）
    action?: 'go-search' | 'go-graph' | 'go-docs' | 'go-chunks' | 'go-settings' | 'clear-chat' | 'show-help' | 'toggle-kb-picker' | 'export-chat'
}

export const SLASH_COMMANDS: SlashCommand[] = [
    // ---------- 导航类 ----------
    {
        cmd: 'search',
        aliases: ['s', 'find'],
        label: '搜索',
        description: '跳转到混合检索页面，输入关键词搜索',
        icon: '🔍',
        category: 'navigation',
        placeholder: '搜索：',
        action: 'go-search'
    },
    {
        cmd: 'graph',
        aliases: ['g', 'kg'],
        label: '知识图谱',
        description: '跳转到知识图谱页面，浏览实体关系',
        icon: '🕸️',
        category: 'navigation',
        action: 'go-graph'
    },
    {
        cmd: 'docs',
        aliases: ['d', 'doc', 'documents'],
        label: '文档管理',
        description: '跳转到文档管理页面，查看/管理已上传文档',
        icon: '📚',
        category: 'navigation',
        action: 'go-docs'
    },
    {
        cmd: 'chunks',
        aliases: ['c', 'vectors'],
        label: '向量分块',
        description: '跳转到向量分块运维页面，查看 chunk 详情',
        icon: '🧩',
        category: 'navigation',
        action: 'go-chunks'
    },
    {
        cmd: 'settings',
        aliases: ['config'],
        label: '系统设置',
        description: '跳转到系统设置，配置 LLM/Embedding/分块',
        icon: '⚙️',
        category: 'navigation',
        action: 'go-settings'
    },

    // ---------- 操作类 ----------
    {
        cmd: 'clear',
        aliases: ['reset', 'new'],
        label: '清空对话',
        description: '清空当前会话的所有消息，开始新对话',
        icon: '🧹',
        category: 'action',
        action: 'clear-chat'
    },
    {
        cmd: 'export',
        aliases: ['save', 'download'],
        label: '导出对话',
        description: '导出当前会话为 Markdown 文件',
        icon: '💾',
        category: 'action',
        action: 'export-chat'
    },
    {
        cmd: 'category',
        aliases: ['cat', 'filter'],
        label: '选择分类',
        description: '限制本次对话/搜索的知识库分类',
        icon: '🏷️',
        category: 'kb',
        action: 'toggle-kb-picker'
    },

    // ---------- 工具类 ----------
    {
        cmd: 'help',
        aliases: ['?', 'h'],
        label: '帮助',
        description: '显示所有可用指令和快捷键',
        icon: '❓',
        category: 'utility',
        action: 'show-help'
    },
    {
        cmd: 'summarize',
        aliases: ['sum'],
        label: '总结当前对话',
        description: '让 AI 总结本次会话的关键内容',
        icon: '📝',
        category: 'utility',
        placeholder: '请总结我们刚才的对话要点',
        action: 'insert-text-and-send'  // 特殊：插入并发送
    }
]

/**
 * 根据用户输入的关键词过滤指令
 * 匹配规则：
 * 1. 完整匹配 cmd（高优先级）
 * 2. cmd 开头匹配
 * 3. alias 匹配
 * 4. label 中文包含
 */
export function filterCommands(keyword: string): SlashCommand[] {
    if (!keyword) return SLASH_COMMANDS
    const k = keyword.toLowerCase()
    return SLASH_COMMANDS.filter(c =>
        c.cmd.toLowerCase().includes(k) ||
        c.cmd.toLowerCase().startsWith(k) ||
        c.aliases?.some(a => a.toLowerCase().includes(k)) ||
        c.label.toLowerCase().includes(k) ||
        c.description.toLowerCase().includes(k)
    )
}
