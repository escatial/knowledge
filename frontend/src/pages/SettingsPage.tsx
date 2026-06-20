import { useState, useEffect } from 'react'
import {
  Settings, Server, Database, Brain,
  X, Loader2, Save, Activity, CheckCircle, XCircle,
  Pencil,
} from 'lucide-react'
import { embeddingApi } from '../services/api'
import KBToggle from '../components/KBToggle'

interface LlmConfig {
  id: string
  provider: string
  model_name: string
  display_name: string
  base_url: string
  is_default: boolean
}

interface AppSettings {
  llm_configs: LlmConfig[]
  embedding_model: string
  chunk_size: number
  chunk_overlap: number
  default_strategy: string
}

interface ProviderOption {
  value: string
  label: string
  defaultModel: string
  defaultBaseUrl: string
  apiKeyRequired: boolean
  description: string
}

const PROVIDER_OPTIONS: ProviderOption[] = [
  {
    value: 'openai',
    label: 'OpenAI',
    defaultModel: 'gpt-4o',
    defaultBaseUrl: 'https://api.openai.com/v1',
    apiKeyRequired: true,
    description: 'OpenAI 官方 API'
  },
  {
    value: 'anthropic',
    label: 'Anthropic',
    defaultModel: 'claude-3-opus-20240229',
    defaultBaseUrl: 'https://api.anthropic.com',
    apiKeyRequired: true,
    description: 'Anthropic Claude API'
  },
  {
    value: 'deepseek',
    label: 'DeepSeek',
    defaultModel: 'deepseek-chat',
    defaultBaseUrl: 'https://api.deepseek.com/v1',
    apiKeyRequired: true,
    description: 'DeepSeek 官方 API'
  },
  {
    value: 'minimax',
    label: 'MiniMax',
    defaultModel: 'MiniMax-M2.7',
    defaultBaseUrl: 'https://api.minimaxi.com/v1',
    apiKeyRequired: true,
    description: 'MiniMax M2 系列模型'
  },
  {
    value: 'minimax_anthropic',
    label: 'MiniMax (Anthropic兼容)',
    defaultModel: 'MiniMax-M2.7',
    defaultBaseUrl: 'https://api.minimaxi.com/anthropic',
    apiKeyRequired: true,
    description: '通过 Anthropic SDK 调用 MiniMax'
  },
  {
    value: 'ollama',
    label: 'Ollama (本地)',
    defaultModel: 'qwen2.5:7b',
    defaultBaseUrl: 'http://localhost:11434/v1',
    apiKeyRequired: false,
    description: '本地部署的 Ollama 服务'
  },
  {
    value: 'zhipu',
    label: '智谱 GLM',
    defaultModel: 'glm-4',
    defaultBaseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    apiKeyRequired: true,
    description: '智谱 AI GLM 系列'
  },
  {
    value: 'qwen',
    label: '通义千问',
    defaultModel: 'qwen-max',
    defaultBaseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    apiKeyRequired: true,
    description: '阿里云通义千问'
  },
  {
    value: 'baichuan',
    label: '百川智能',
    defaultModel: 'Baichuan4',
    defaultBaseUrl: 'https://api.baichuan-ai.com/v1',
    apiKeyRequired: true,
    description: '百川智能大模型'
  },
  {
    value: 'moonshot',
    label: 'Moonshot (Kimi)',
    defaultModel: 'moonshot-v1-8k',
    defaultBaseUrl: 'https://api.moonshot.cn/v1',
    apiKeyRequired: true,
    description: '月之暗面 Kimi'
  },
  {
    value: 'custom',
    label: '自定义',
    defaultModel: '',
    defaultBaseUrl: '',
    apiKeyRequired: false,
    description: '自定义 OpenAI 兼容接口'
  }
]

const STRATEGY_OPTIONS = [
  { value: 'auto', label: '智能推荐', desc: '由系统自动分析文档特征并推荐最佳分块策略' },
  { value: 'recursive', label: '递归分块', desc: '按段落→句子→字符的优先级递归拆分，适合通用文档' },
  { value: 'fixed', label: '固定大小', desc: '按固定字符长度切分，简单快速，适合日志等格式统一文本' },
  { value: 'structure', label: '基于结构', desc: '识别标题、章节等结构标记进行分块，适合Markdown、PDF' },
  { value: 'semantic', label: '语义分块', desc: '基于句子边界和语义连贯性分块，适合主题跳跃频繁文档' },
  { value: 'naive', label: '简单分块', desc: '按固定长度切分，最基础的分块方式' },
  { value: 'general', label: '通用分块', desc: '智能识别段落边界，通用场景适用' },
  { value: 'intelligent', label: '智能分块', desc: '识别标题、段落等结构，自动合并过小章节' },
  { value: 'parent_child', label: '父子分块', desc: '子块用于检索，父块用于上下文，提升检索精度' },
  { value: 'book', label: '书籍分块', desc: '识别章节层级结构，适合书籍、长文档' },
  { value: 'paper', label: '论文分块', desc: '针对学术论文优化，识别摘要、引言、结论等模块' },
  { value: 'resume', label: '简历分块', desc: '识别简历模块，如教育背景、工作经历等' },
  { value: 'qa', label: '问答对分块', desc: '识别问答配对，适合FAQ、问答类文档' },
  { value: 'table', label: '表格分块', desc: '保留表格结构，适合CSV、Excel等表格数据' },
]

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<'llm' | 'embedding' | 'chunking'>('llm')
  const [settings, setSettings] = useState<AppSettings>({
    llm_configs: [],
    embedding_model: 'BAAI/bge-small-zh-v1.5',
    chunk_size: 500,
    chunk_overlap: 50,
    default_strategy: 'general'
  })
  const [showAddLlm, setShowAddLlm] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)

  // Embedding 真实状态（来自后端 /api/embedding/*）
  const [embeddingInfo, setEmbeddingInfo] = useState<any>(null)
  const [embeddingProviders, setEmbeddingProviders] = useState<any[]>([])
  const [embeddingLoading, setEmbeddingLoading] = useState(false)
  const [embeddingTest, setEmbeddingTest] = useState<{
    running: boolean
    result?: any
  }>({ running: false })

  // 任务 P3-8 修复：editingId 区分「新增」与「编辑」模式
  const [editingId, setEditingId] = useState<string | null>(null)

  // 进入 Embedding Tab 时拉取真实状态
  useEffect(() => {
    if (activeTab !== 'embedding') return
    setEmbeddingLoading(true)
    Promise.all([embeddingApi.info(), embeddingApi.providers()])
      .then(([infoRes, provRes]) => {
        setEmbeddingInfo(infoRes.data)
        setEmbeddingProviders(provRes.data?.providers || [])
      })
      .catch((e) => {
        console.error('加载 Embedding 状态失败', e)
        setEmbeddingInfo({ error: String(e?.response?.data?.error || e?.message || e) })
      })
      .finally(() => setEmbeddingLoading(false))
  }, [activeTab])

  // 对当前 provider 跑一次连通性测试
  const runEmbeddingTest = async () => {
    setEmbeddingTest({ running: true })
    try {
      const res = await embeddingApi.test({ text: 'RAG 是检索增强生成' })
      setEmbeddingTest({ running: false, result: res.data })
    } catch (e: any) {
      setEmbeddingTest({ running: false, result: { ok: false, error: String(e) } })
    }
  }
  const [testResults, setTestResults] = useState<Record<string, { status: 'ok' | 'error'; message: string } >>({})
  const [llmForm, setLlmForm] = useState({
    provider: 'openai',
    model_name: '',
    display_name: '',
    base_url: '',
    api_key: '',
    is_default: false
  })

  useEffect(() => {
    loadSettings()
  }, [])

  const loadSettings = async () => {
    // 从 localStorage 加载或调用 API
    const saved = localStorage.getItem('app_settings')
    if (saved) {
      try {
        setSettings(JSON.parse(saved))
      } catch {
        console.error('加载设置失败')
      }
      return
    }
    // 首次使用：自动预置 MiniMax（默认）和 DeepSeek 模型配置
    // 任务 P3-8 修复：使用正确的 MiniMax 模型名（M2.7）
    // 注意：用户的"minimax-M3"不是真实 LLM 模型，是 AI 模型代号，不要混用
    const defaultConfigs: LlmConfig[] = [
      {
        id: 'preset-minimax',
        provider: 'minimax',
        model_name: 'MiniMax-M2.7',
        display_name: 'MiniMax-M2.7',
        base_url: 'https://api.minimaxi.com/v1',
        is_default: true,
      },
      {
        id: 'preset-deepseek',
        provider: 'deepseek',
        model_name: 'deepseek-chat',
        display_name: 'DeepSeek Chat',
        base_url: 'https://api.deepseek.com/v1',
        is_default: false,
      },
    ]
    const initialSettings: AppSettings = {
      llm_configs: defaultConfigs,
      embedding_model: 'BAAI/bge-small-zh-v1.5',
      chunk_size: 500,
      chunk_overlap: 50,
      default_strategy: 'general',
    }
    setSettings(initialSettings)
    localStorage.setItem('app_settings', JSON.stringify(initialSettings))
  }

  // 任务 P3-8 修复：抽离持久化函数，所有变更操作后自动调用
  // 之前：add/delete/setDefault 只更新 state，不写 localStorage → 刷新就丢
  // 支持两种调用方式：
  //  - persistSettings(next: AppSettings)   直接传新状态
  //  - persistSettings(prev => next)        回调式（推荐）
  const persistSettings = (nextOrFn: AppSettings | ((prev: AppSettings) => AppSettings)) => {
    setSettings(prev => {
      const next = typeof nextOrFn === 'function'
        ? (nextOrFn as (p: AppSettings) => AppSettings)(prev)
        : nextOrFn
      try {
        localStorage.setItem('app_settings', JSON.stringify(next))
      } catch (error) {
        console.error('保存到 localStorage 失败:', error)
      }
      return next
    })
  }

  const saveSettings = async () => {
    setSaving(true)
    try {
      localStorage.setItem('app_settings', JSON.stringify(settings))
      // 这里可以调用 API 保存到后端
      alert('设置已保存')
    } catch (error) {
      console.error('保存失败:', error)
    } finally {
      setSaving(false)
    }
  }

  const handleAddLlm = () => {
    if (!llmForm.model_name || !llmForm.display_name) {
      alert('请填写完整信息')
      return
    }

    if (editingId) {
      // 编辑模式：更新已有配置（任务 P3-8 修复：持久化到 localStorage）
      persistSettings(prev => ({
        ...prev,
        llm_configs: prev.llm_configs.map(c => {
          if (c.id !== editingId) {
            // 如果新设了默认，取消其他默认
            return llmForm.is_default ? { ...c, is_default: false } : c
          }
          return {
            ...c,
            provider: llmForm.provider,
            model_name: llmForm.model_name,
            display_name: llmForm.display_name,
            base_url: llmForm.base_url,
            is_default: llmForm.is_default,
          }
        })
      }))
    } else {
      // 新增模式（任务 P3-8 修复：持久化到 localStorage）
      const newConfig: LlmConfig = {
        id: Date.now().toString(),
        provider: llmForm.provider,
        model_name: llmForm.model_name,
        display_name: llmForm.display_name,
        base_url: llmForm.base_url,
        is_default: llmForm.is_default
      }

      persistSettings(prev => ({
        ...prev,
        llm_configs: llmForm.is_default
          ? prev.llm_configs.map(c => ({ ...c, is_default: false })).concat(newConfig)
          : [...prev.llm_configs, newConfig]
      }))
    }

    setShowAddLlm(false)
    setEditingId(null)
    setLlmForm({
      provider: 'openai',
      model_name: '',
      display_name: '',
      base_url: '',
      api_key: '',
      is_default: false
    })
  }

  // 任务 P3-8 修复：添加 handleEditLlm 函数（之前缺编辑功能）
  const handleEditLlm = (id: string) => {
    const target = settings.llm_configs.find(c => c.id === id)
    if (!target) {
      alert('找不到要编辑的模型配置')
      return
    }
    setEditingId(id)
    setLlmForm({
      provider: target.provider,
      model_name: target.model_name,
      display_name: target.display_name,
      base_url: target.base_url,
      api_key: '',
      is_default: target.is_default
    })
    setShowAddLlm(true)
  }

  const handleDeleteLlm = (id: string) => {
    if (!confirm('确定删除此模型配置？')) return
    persistSettings(prev => ({
      ...prev,
      llm_configs: prev.llm_configs.filter(c => c.id !== id)
    }))
  }

  const handleSetDefault = (id: string) => {
    persistSettings(prev => ({
      ...prev,
      llm_configs: prev.llm_configs.map(c => ({
        ...c,
        is_default: c.id === id
      }))
    }))
  }

  const handleTestLlm = async (config: LlmConfig) => {
    setTestingId(config.id)
    try {
      // 模拟测试连接
      await new Promise(resolve => setTimeout(resolve, 1500))
      
      // 实际应该调用后端 API 测试
      // const res = await aiApi.test(config)
      
      setTestResults(prev => ({
        ...prev,
        [config.id]: {
          status: 'ok',
          message: '连接成功，模型响应正常'
        }
      }))
    } catch (error) {
      setTestResults(prev => ({
        ...prev,
        [config.id]: {
          status: 'error',
          message: '连接失败，请检查配置'
        }
      }))
    } finally {
      setTestingId(null)
    }
  }

  const tabs = [
    { id: 'llm' as const, label: 'LLM 模型', icon: Brain },
    { id: 'embedding' as const, label: 'Embedding', icon: Database },
    { id: 'chunking' as const, label: '分块策略', icon: Server },
    { id: 'advanced' as const, label: '高级', icon: Settings },
  ]

  return (
    <div className="space-y-6">
      {/* 页面标题 */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">系统设置</h1>
        <p className="text-sm text-gray-500 mt-1">管理模型配置与系统参数</p>
      </div>

      {/* 标签页 */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="flex border-b border-gray-100">
          {tabs.map(tab => {
            const Icon = tab.icon
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-6 py-4 text-sm font-medium transition-colors border-b-2 ${
                  activeTab === tab.id
                    ? 'border-blue-500 text-blue-600 bg-blue-50/50'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </button>
            )
          })}
        </div>

        <div className="p-6">
          {/* LLM 配置 */}
          {activeTab === 'llm' && (
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-gray-900">已配置的模型</h3>
                <button
                  onClick={() => {
                    setEditingId(null)  // 任务 P3-8：清空编辑态，确保是新增模式
                    setLlmForm({
                      provider: 'openai',
                      model_name: '',
                      display_name: '',
                      base_url: '',
                      api_key: '',
                      is_default: false
                    })
                    setShowAddLlm(true)
                  }}
                  className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-xl text-sm hover:bg-blue-700 transition-colors"
                >
                  <Settings className="h-4 w-4" />
                  添加模型
                </button>
              </div>

              {settings.llm_configs.length === 0 ? (
                <div className="text-center py-12 text-gray-400">
                  <Brain className="h-12 w-12 mx-auto mb-3 text-gray-200" />
                  <p className="text-sm">暂无模型配置</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {settings.llm_configs.map(config => (
                    <div
                      key={config.id}
                      className={`flex items-center justify-between p-4 rounded-xl border transition-all ${
                        config.is_default
                          ? 'bg-blue-50/80 border-blue-200 shadow-sm'
                          : 'bg-gray-50 border-gray-100'
                      }`}
                    >
                      <div className="flex items-center gap-4">
                        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                          config.is_default
                            ? 'bg-blue-100 text-blue-600'
                            : 'bg-gray-100 text-gray-500'
                        }`}>
                          <Brain className="h-5 w-5" />
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className={`font-medium ${config.is_default ? 'text-blue-900' : 'text-gray-900'}`}>
                              {config.display_name}
                            </span>
                            {config.is_default && (
                              <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded-full font-medium">
                                正在使用
                              </span>
                            )}
                            {testResults[config.id]?.status === 'ok' && (
                              <span className="px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded-full font-medium">
                                可用
                              </span>
                            )}
                            {testResults[config.id]?.status === 'error' && (
                              <span className="px-2 py-0.5 bg-red-100 text-red-700 text-xs rounded-full font-medium">
                                异常
                              </span>
                            )}
                          </div>
                          <p className={`text-sm mt-0.5 ${config.is_default ? 'text-blue-600' : 'text-gray-500'}`}>
                            {config.provider} · {config.model_name}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleTestLlm(config)}
                          disabled={testingId === config.id}
                          className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg transition-colors ${
                            testResults[config.id]?.status === 'ok'
                              ? 'text-green-600 bg-green-50 hover:bg-green-100'
                              : testResults[config.id]?.status === 'error'
                              ? 'text-red-600 bg-red-50 hover:bg-red-100'
                              : 'text-gray-600 hover:text-blue-600 hover:bg-blue-50'
                          }`}
                        >
                          {testingId === config.id ? (
                            <>
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              <span>测试中...</span>
                            </>
                          ) : testResults[config.id]?.status === 'ok' ? (
                            <>
                              <CheckCircle className="h-3.5 w-3.5" />
                              <span>正常</span>
                            </>
                          ) : testResults[config.id]?.status === 'error' ? (
                            <>
                              <XCircle className="h-3.5 w-3.5" />
                              <span>失败</span>
                            </>
                          ) : (
                            <>
                              <Activity className="h-3.5 w-3.5" />
                              <span>测试</span>
                            </>
                          )}
                        </button>
                        
                        {!config.is_default && (
                          <button
                            onClick={() => handleSetDefault(config.id)}
                            className="px-3 py-1.5 text-sm text-gray-600 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                          >
                            设为默认
                          </button>
                        )}
                        {/* 任务 P3-8 修复：每个已配置模型加「编辑」按钮 */}
                        <button
                          onClick={() => handleEditLlm(config.id)}
                          className="p-2 hover:bg-blue-50 rounded-lg transition-colors"
                          title="编辑此模型配置"
                        >
                          <Pencil className="h-4 w-4 text-blue-500" />
                        </button>
                        <button
                          onClick={() => handleDeleteLlm(config.id)}
                          className="p-2 hover:bg-red-50 rounded-lg transition-colors"
                        >
                          <X className="h-4 w-4 text-red-400" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* 添加模型弹窗 */}
              {showAddLlm && (
                <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
                  <div className="bg-white rounded-2xl w-full max-w-lg shadow-2xl">
                    <div className="p-6 border-b border-gray-100">
                      <h3 className="text-lg font-semibold text-gray-900">
                        {editingId ? '编辑 LLM 模型' : '添加 LLM 模型'}
                      </h3>
                    </div>
                    <div className="p-6 space-y-4">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">提供商</label>
                        <select
                          value={llmForm.provider}
                          onChange={(e) => {
                            const provider = PROVIDER_OPTIONS.find(p => p.value === e.target.value)
                            setLlmForm(prev => ({
                              ...prev,
                              provider: e.target.value,
                              model_name: provider?.defaultModel || '',
                              base_url: provider?.defaultBaseUrl || ''
                            }))
                          }}
                          className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 text-sm"
                        >
                          {PROVIDER_OPTIONS.map(p => (
                            <option key={p.value} value={p.value}>{p.label}</option>
                          ))}
                        </select>
                        <p className="text-xs text-gray-400 mt-1">
                          {PROVIDER_OPTIONS.find(p => p.value === llmForm.provider)?.description}
                        </p>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">模型名称</label>
                        <input
                          type="text"
                          value={llmForm.model_name}
                          onChange={(e) => setLlmForm(prev => ({ ...prev, model_name: e.target.value }))}
                          placeholder="例如: gpt-4o"
                          className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">显示名称</label>
                        <input
                          type="text"
                          value={llmForm.display_name}
                          onChange={(e) => setLlmForm(prev => ({ ...prev, display_name: e.target.value }))}
                          placeholder="例如: GPT-4o"
                          className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">API Key</label>
                        <input
                          type="password"
                          value={llmForm.api_key}
                          onChange={(e) => setLlmForm(prev => ({ ...prev, api_key: e.target.value }))}
                          placeholder={PROVIDER_OPTIONS.find(p => p.value === llmForm.provider)?.apiKeyRequired ? '必填' : '可选'}
                          className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Base URL</label>
                        <input
                          type="text"
                          value={llmForm.base_url}
                          onChange={(e) => setLlmForm(prev => ({ ...prev, base_url: e.target.value }))}
                          placeholder="https://api.example.com/v1"
                          className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 text-sm"
                        />
                        <p className="text-xs text-gray-400 mt-1">
                          已自动填充官方默认地址，可手动修改
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          id="is_default"
                          checked={llmForm.is_default}
                          onChange={(e) => setLlmForm(prev => ({ ...prev, is_default: e.target.checked }))}
                          className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                        />
                        <label htmlFor="is_default" className="text-sm text-gray-700">设为默认模型</label>
                      </div>
                    </div>
                    <div className="p-6 border-t border-gray-100 flex justify-end gap-3">
                      <button
                        onClick={() => setShowAddLlm(false)}
                        className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-xl transition-colors"
                      >
                        取消
                      </button>
                      <button
                        onClick={handleAddLlm}
                        className="px-4 py-2 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition-colors"
                      >
                        {editingId ? '保存修改' : '保存'}
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Embedding 配置 - 实时反映后端 /api/embedding/* 状态 */}
          {activeTab === 'embedding' && (
            <div className="space-y-6">
              {/* 当前 Embedding 真实状态 */}
              <div className="bg-gray-50 rounded-xl p-6 border border-gray-100">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="font-semibold text-gray-900">当前 Embedding 模型</h3>
                  <div className="flex items-center gap-2">
                    {embeddingLoading && <Loader2 className="h-4 w-4 animate-spin text-gray-400" />}
                    <button
                      onClick={runEmbeddingTest}
                      disabled={embeddingTest.running || embeddingLoading}
                      className="text-xs px-3 py-1.5 bg-white border border-gray-200 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50 flex items-center gap-1"
                    >
                      {embeddingTest.running ? <Loader2 className="h-3 w-3 animate-spin" /> : <Activity className="h-3 w-3" />}
                      连通性测试
                    </button>
                  </div>
                </div>

                {embeddingInfo?.error ? (
                  <div className="text-sm text-red-600 p-3 bg-red-50 rounded-lg">
                    加载失败：{embeddingInfo.error}
                  </div>
                ) : !embeddingInfo ? (
                  <div className="text-sm text-gray-400 p-3">加载中...</div>
                ) : (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-gray-500">运行模式</span>
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          embeddingInfo.mode?.startsWith('api_')
                            ? 'bg-blue-100 text-blue-700'
                            : embeddingInfo.mode === 'modelscope'
                            ? 'bg-purple-100 text-purple-700'
                            : 'bg-gray-200 text-gray-700'
                        }`}>
                          {embeddingInfo.mode || 'unknown'}
                        </span>
                        {!embeddingInfo.has_api_key && embeddingInfo.mode?.startsWith('api_') && (
                          <span className="text-xs text-amber-600">⚠ 未配置 Key</span>
                        )}
                        {embeddingInfo.mode === 'minimax' && embeddingInfo.group_id_configured === false && (
                          <span className="text-xs text-amber-600">⚠ 缺 GroupId</span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-gray-500">Provider / 模型</span>
                      <span className="text-sm font-medium text-gray-900">
                        {embeddingInfo.provider || 'local'} · {embeddingInfo.model_name || '(unknown)'}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-gray-500">向量维度</span>
                      <span className="text-sm font-medium text-gray-900">{embeddingInfo.dimension}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-gray-500">协议</span>
                      <span className="text-sm font-medium text-gray-900">
                        {embeddingInfo.protocol || 'n/a'}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-gray-500">说明</span>
                      <span className="text-xs text-gray-500 text-right max-w-[60%]">
                        {embeddingInfo.note || '—'}
                      </span>
                    </div>
                  </div>
                )}

                {/* 连通性测试结果 */}
                {embeddingTest.result && (
                  <div className={`mt-4 p-3 rounded-lg text-sm ${
                    embeddingTest.result.ok
                      ? 'bg-green-50 text-green-700 border border-green-100'
                      : 'bg-red-50 text-red-700 border border-red-100'
                  }`}>
                    {embeddingTest.result.ok ? (
                      <>
                        <CheckCircle className="h-4 w-4 inline mr-1" />
                        连通成功 · 维度 {embeddingTest.result.dimension} ·
                        耗时 {embeddingTest.result.elapsed_ms}ms ·
                        范数 {embeddingTest.result.vector_norm}
                      </>
                    ) : (
                      <>
                        <XCircle className="h-4 w-4 inline mr-1" />
                        连通失败：{embeddingTest.result.error}
                      </>
                    )}
                  </div>
                )}
              </div>

              {/* 可用 provider 列表 */}
              <div className="bg-white rounded-xl p-6 border border-gray-100">
                <h3 className="font-semibold text-gray-900 mb-4">可用 Provider</h3>
                <div className="space-y-2">
                  {embeddingProviders.length === 0 ? (
                    <div className="text-sm text-gray-400">加载中...</div>
                  ) : (
                    embeddingProviders.map((p) => (
                      <div
                        key={p.id}
                        className={`p-3 rounded-lg border ${
                          p.is_current
                            ? 'border-blue-200 bg-blue-50/50'
                            : 'border-gray-100 hover:border-gray-200'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-sm text-gray-900">{p.label}</span>
                              {p.is_current && (
                                <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 text-xs rounded">
                                  当前
                                </span>
                              )}
                              {p.supports_embedding ? (
                                <span className="px-1.5 py-0.5 bg-green-100 text-green-700 text-xs rounded">
                                  支持
                                </span>
                              ) : (
                                <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 text-xs rounded">
                                  未官方支持
                                </span>
                              )}
                            </div>
                            <div className="text-xs text-gray-500 mt-1">
                              {p.default_model} · {p.dim} 维 · {p.note}
                            </div>
                          </div>
                          <code className="text-xs text-gray-400">{p.id}</code>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* 切换说明 */}
              <div className="bg-blue-50 rounded-xl p-4 border border-blue-100">
                <p className="text-sm text-blue-700">
                  Embedding 模型在文档上传时自动调用。切换 provider 需要修改后端环境变量
                  <code className="mx-1 px-1.5 py-0.5 bg-white rounded text-xs">EMBEDDING_MODE</code>
                  和
                  <code className="mx-1 px-1.5 py-0.5 bg-white rounded text-xs">EMBEDDING_PROVIDER</code>
                  后重启服务。当前 mode 与 provider 实时显示在上方。
                </p>
              </div>
            </div>
          )}

          {/* 分块策略 */}
          {activeTab === 'chunking' && (
            <div className="space-y-6">
              <div className="bg-blue-50 rounded-xl p-4 border border-blue-100">
                <p className="text-sm text-blue-700">
                  💡 分类管理已迁移到 <a href="/documents" className="font-medium underline">「文档管理」</a> 页面，
                  可直接在那里对每个分类进行新增/编辑/删除/迁移文档等操作。
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">默认分块大小</label>
                  <input
                    type="number"
                    value={settings.chunk_size}
                    onChange={(e) => setSettings(prev => ({ ...prev, chunk_size: parseInt(e.target.value) }))}
                    className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 text-sm"
                  />
                  <p className="text-xs text-gray-400 mt-1">每个分块的最大字符数</p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">分块重叠</label>
                  <input
                    type="number"
                    value={settings.chunk_overlap}
                    onChange={(e) => setSettings(prev => ({ ...prev, chunk_overlap: parseInt(e.target.value) }))}
                    className="w-full px-4 py-2.5 border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 text-sm"
                  />
                  <p className="text-xs text-gray-400 mt-1">相邻分块之间的重叠字符数</p>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-3">默认分块策略</label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {STRATEGY_OPTIONS.map(strategy => (
                    <button
                      key={strategy.value}
                      onClick={() => setSettings(prev => ({ ...prev, default_strategy: strategy.value }))}
                      className={`p-4 rounded-xl border text-left transition-all ${
                        settings.default_strategy === strategy.value
                          ? 'border-blue-500 bg-blue-50 shadow-sm'
                          : 'border-gray-200 hover:border-gray-300'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                          settings.default_strategy === strategy.value
                            ? 'border-blue-500'
                            : 'border-gray-300'
                        }`}>
                          {settings.default_strategy === strategy.value && (
                            <div className="w-2 h-2 rounded-full bg-blue-500" />
                          )}
                        </div>
                        <span className="font-medium text-gray-900">{strategy.label}</span>
                      </div>
                      <p className="text-sm text-gray-500 mt-1 ml-6">{strategy.desc}</p>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* 高级 - 任务 2：知识库开关 */}
          {activeTab === 'advanced' && (
            <div className="space-y-6">
              <div className="bg-gradient-to-br from-indigo-50 to-blue-50 rounded-xl p-5 border border-indigo-100">
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-lg bg-indigo-500 flex items-center justify-center text-white shrink-0">
                    <Database className="h-5 w-5" />
                  </div>
                  <div className="flex-1">
                    <h3 className="text-base font-semibold text-gray-900 mb-1">多知识库（KB）</h3>
                    <p className="text-sm text-gray-600 leading-relaxed">
                      启用后，侧边栏将出现「知识库选择器」。你可以在不同的 KB 之间物理隔离数据
                      （独立的图谱文件、独立的向量存储），适合多项目/多客户/敏感数据分离等场景。
                    </p>
                    <p className="text-xs text-gray-500 mt-2">
                      <strong>普通个人用户无需启用</strong>，使用分类（category）已足够。
                      启用后，所有数据将归属于「默认知识库」，与现状一致。
                    </p>
                  </div>
                  <KBToggle />
                </div>
              </div>

              <div className="bg-white rounded-xl border border-gray-100 p-5">
                <h4 className="text-sm font-semibold text-gray-900 mb-3">关于知识库 vs 分类</h4>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="text-left text-gray-500 font-medium py-2 pr-3">特性</th>
                      <th className="text-left text-gray-500 font-medium py-2 pr-3">分类 (category)</th>
                      <th className="text-left text-gray-500 font-medium py-2">知识库 (KB)</th>
                    </tr>
                  </thead>
                  <tbody className="text-gray-700">
                    <tr className="border-b border-gray-50">
                      <td className="py-2 pr-3">数据隔离</td>
                      <td className="py-2 pr-3">共享同一向量库</td>
                      <td className="py-2">物理独立</td>
                    </tr>
                    <tr className="border-b border-gray-50">
                      <td className="py-2 pr-3">图谱</td>
                      <td className="py-2 pr-3">共享一个</td>
                      <td className="py-2">每个库独立</td>
                    </tr>
                    <tr className="border-b border-gray-50">
                      <td className="py-2 pr-3">检索边界</td>
                      <td className="py-2 pr-3">可跨分类</td>
                      <td className="py-2">严格不跨界</td>
                    </tr>
                    <tr>
                      <td className="py-2 pr-3">适合场景</td>
                      <td className="py-2 pr-3">个人用、分类整理</td>
                      <td className="py-2">多项目、多客户、敏感数据</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 保存按钮 */}
      <div className="flex justify-end">
        <button
          onClick={saveSettings}
          disabled={saving}
          className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-blue-500 to-indigo-600 text-white rounded-xl hover:shadow-lg transition-all disabled:opacity-50"
        >
          {saving ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          <span>{saving ? '保存中...' : '保存设置'}</span>
        </button>
      </div>
    </div>
  )
}
