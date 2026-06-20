import { useEffect, useState } from 'react'
import { FileText, Database, Network, Layers } from 'lucide-react'
import { documentApi, graphApi } from '../services/api'

interface StatsData {
  documents: number
  vectors: number
  nodes: number
  edges: number
}

export default function DashboardStats() {
  const [stats, setStats] = useState<StatsData>({
    documents: 0,
    vectors: 0,
    nodes: 0,
    edges: 0
  })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadStats()
  }, [])

  const loadStats = async () => {
    setLoading(true)
    try {
      const [docRes, vectorRes, graphRes] = await Promise.all([
        documentApi.list(),
        documentApi.vectorStats(),
        graphApi.getGraph()
      ])

      setStats({
        documents: docRes.data?.length || 0,
        vectors: vectorRes.data?.total_chunks || 0,
        nodes: graphRes.data?.nodes?.length || 0,
        edges: graphRes.data?.edges?.length || 0
      })
    } catch (error) {
      console.error('加载统计数据失败:', error)
    } finally {
      setLoading(false)
    }
  }

  const cards = [
    {
      title: '文档总数',
      value: stats.documents,
      icon: FileText,
      color: 'bg-blue-500',
      bgColor: 'bg-blue-50',
      textColor: 'text-blue-600'
    },
    {
      title: '向量块数',
      value: stats.vectors,
      icon: Database,
      color: 'bg-green-500',
      bgColor: 'bg-green-50',
      textColor: 'text-green-600'
    },
    {
      title: '图谱节点',
      value: stats.nodes,
      icon: Network,
      color: 'bg-purple-500',
      bgColor: 'bg-purple-50',
      textColor: 'text-purple-600'
    },
    {
      title: '关系连线',
      value: stats.edges,
      icon: Layers,
      color: 'bg-orange-500',
      bgColor: 'bg-orange-50',
      textColor: 'text-orange-600'
    }
  ]

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((card) => {
        const Icon = card.icon
        return (
          <div
            key={card.title}
            className={`${card.bgColor} rounded-xl p-5 border border-gray-100 hover:shadow-md transition-shadow`}
          >
            <div className="flex items-center justify-between mb-3">
              <div className={`${card.color} p-2 rounded-lg`}>
                <Icon className="h-5 w-5 text-white" />
              </div>
              {loading && (
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-400" />
              )}
            </div>
            <p className={`text-2xl font-bold ${card.textColor}`}>
              {loading ? '-' : card.value}
            </p>
            <p className="text-sm text-gray-500 mt-1">{card.title}</p>
          </div>
        )
      })}
    </div>
  )
}
