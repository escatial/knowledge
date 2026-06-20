import axios from 'axios'

// 基础配置
const api = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 长超时实例（用于上传、解析等耗时操作）
const longApi = axios.create({
  baseURL: '/api',
  timeout: 300000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 文档 API
export const documentApi = {
  upload: (file: File, title?: string, category?: string, strategy?: string) => {
    const formData = new FormData()
    formData.append('file', file)
    if (title) formData.append('title', title)
    if (category) formData.append('category', category)
    if (strategy) formData.append('strategy', strategy)
    return longApi.post('/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  getProgress: (taskId: string) => {
    return api.get(`/documents/progress/${taskId}`)
  },

  list: (category?: string, knowledgeBaseId?: string) => {
    return api.get('/documents/list', { params: { category, knowledge_base_id: knowledgeBaseId || 'all' } })
  },

  delete: (id: string) => {
    return api.delete(`/documents/${id}`)
  },

  /** 修改文档的分类（同步向量库元数据 + 操作日志） */
  updateCategory: (id: string, category: string, operator = 'admin') => {
    return api.put(`/documents/${id}/category`, null, { params: { category, operator } })
  },

  /** 批量迁移文档至新分类（任务 4） */
  migrateBatch: (docIds: string[], targetCategory: string, operator = 'admin') => {
    return api.post('/documents/migrate-batch', { doc_ids: docIds, target_category: targetCategory }, { params: { operator } })
  },

  /** 任务 2.2：批量迁移 + SSE 流式进度（支持失败重试：只传 failed_ids） */
  migrateBatchStream: (docIds: string[], targetCategory: string, owner?: string) => {
    return fetch('/api/documents/migrate-batch-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({
        doc_ids: docIds,
        target_category: targetCategory,
        owner: owner || null,
      }),
    })
  },

  /** 获取迁移操作日志 */
  getOpLog: (limit = 50) => {
    return api.get('/documents/migration-log', { params: { limit } })
  },

  vectorStats: () => {
    return api.get('/documents/stats/vector')
  },

  dashboardStats: () => {
    return api.get('/documents/stats/dashboard')
  },

  syncChatStats: (stats: { total_sessions: number; total_messages: number }) => {
    return api.post('/documents/stats/chat/sync', stats)
  }
}

// 分类 API
export const categoryApi = {
  getAll: () => {
    return api.get('/categories/')
  },

  create: (name: string, strategy?: string, chunkSize?: number, overlap?: number) => {
    return api.post('/categories/', null, {
      params: { name, strategy, chunk_size: chunkSize, overlap }
    })
  },

  update: (name: string, strategy?: string, chunkSize?: number, overlap?: number) => {
    return api.put(`/categories/${name}`, null, {
      params: { strategy, chunk_size: chunkSize, overlap }
    })
  },

  delete: (name: string) => {
    return api.delete(`/categories/${name}`)
  },

  recommend: (text: string, title?: string) => {
    return api.post('/categories/recommend', null, {
      params: { text, title }
    })
  }
}

// 搜索 API
export const searchApi = {
  hybrid: (q: string, limit: number = 10, knowledgeBaseId?: string) => {
    return api.get('/search/', { params: { q, limit, knowledge_base_id: knowledgeBaseId || 'all' } })
  },

  vector: (q: string, top_k: number = 10) => {
    return api.get('/search/vector', { params: { q, top_k } })
  },

  graph: (q: string, depth: number = 2) => {
    return api.get('/search/graph', { params: { q, depth } })
  }
}

// 图谱 API
export const graphApi = {
  getGraph: (knowledgeBaseId?: string) => {
    return api.get('/graph/', { params: { knowledge_base_id: knowledgeBaseId || 'all' } })
  },

  getNodeDetail: (nodeId: string) => {
    return api.get(`/graph/node/${nodeId}`)
  },

  search: (q: string, depth: number = 2, knowledgeBaseId?: string) => {
    return api.get('/graph/search', { params: { q, depth, knowledge_base_id: knowledgeBaseId || 'all' } })
  },
}

// AI API
export const aiApi = {
  ask: (q: string, model?: string, apiKey?: string, baseUrl?: string, knowledgeBaseId?: string) => {
    return api.post('/ai/ask', null, {
      params: { q, model, api_key: apiKey, base_url: baseUrl, knowledge_base_id: knowledgeBaseId || 'all' }
    })
  },

  knowledgeBases: () => {
    return api.get('/ai/knowledge-bases')
  },

  askStream: (q: string, model?: string, apiKey?: string, baseUrl?: string, context?: any[], sessionId?: string, selectedCategories?: string[], knowledgeBaseId?: string) => {
    const params = new URLSearchParams()
    params.append('q', q)
    if (model) params.append('model', model)
    if (apiKey) params.append('api_key', apiKey)
    if (baseUrl) params.append('base_url', baseUrl)
    if (sessionId) params.append('session_id', sessionId)
    if (selectedCategories && selectedCategories.length > 0) {
      selectedCategories.forEach((c) => params.append('selected_categories', c))
    }
    if (knowledgeBaseId) params.append('knowledge_base_id', knowledgeBaseId)
    return fetch(`/api/ai/ask/stream?${params.toString()}`, {
      method: 'POST',
      headers: {
        'Accept': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Content-Type': 'application/json'
      },
      body: context && context.length > 0 ? JSON.stringify({ context }) : undefined
    })
  },

  extract: (text: string, model?: string) => {
    return api.post('/ai/extract', null, { params: { text, model } })
  },

  /** 提交问答任务，立即返回 task_id（后台持久化运行，页面切换不中断） */
  askAsync: (q: string, sessionId?: string, context?: any[], model?: string, selectedCategories?: string[]) => {
    return api.post('/ai/ask/async', null, {
      params: {
        q, session_id: sessionId, model,
        context: context ? JSON.stringify(context) : undefined,
        selected_categories: selectedCategories?.length ? selectedCategories.join(',') : undefined,
      }
    })
  },

  /** 轮询任务状态 */
  getTask: (taskId: string) => {
    return api.get(`/ai/tasks/${taskId}`)
  },

  /** 列出某 session 的所有任务 */
  listTasks: (sessionId: string) => {
    return api.get('/ai/tasks', { params: { session_id: sessionId } })
  },

  /** 删除任务 */
  deleteTask: (taskId: string) => {
    return api.delete(`/ai/tasks/${taskId}`)
  }
}

// Embedding 管理 API
export const embeddingApi = {
  /** 获取当前 embedding 服务详情（mode/dim/model/provider/protocol） */
  info: () => {
    return api.get('/embedding/info')
  },

  /** 列出所有支持的 provider 及其元数据 */
  providers: () => {
    return api.get('/embedding/providers')
  },

  /** 连通性测试 - 实际调用一次 embedding API */
  test: (params: {
    text?: string
    provider?: string
    api_key?: string
    base_url?: string
    model?: string
    mode?: 'db' | 'query'
    group_id?: string
  } = {}) => {
    return api.post('/embedding/test', params)
  },

  /** 对比 db 模式与 query 模式的差异（验证 MiniMax 双模式是否生效） */
  compare: (params: { text?: string; provider?: string } = {}) => {
    return api.post('/embedding/compare', params)
  }
}

// 任务 2：知识库管理 API
export const knowledgeBaseApi = {
  list: () => api.get('/knowledge-bases').then((r) => r.data),
  create: (name: string, description?: string) =>
    api.post('/knowledge-bases', { name, description }).then((r) => r.data),
  delete: (id: string) => api.delete(`/knowledge-bases/${id}`).then((r) => r.data),
  migrate: (docId: string, fromKB: string, toKB: string) =>
    api.post('/knowledge-bases/migrate', { doc_id: docId, from_kb: fromKB, to_kb: toKB }).then((r) => r.data),
}

export default api
