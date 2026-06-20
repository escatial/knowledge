import { useState, useEffect } from 'react'
import { graphApi } from '../services/api'
import { KnowledgeGraph, GraphNode, NodeDetail } from '../types'
import Graph2D from '../components/Graph2D'
import Graph3D from '../components/Graph3D'
import NodeDetailPanel from '../components/NodeDetail'
import DraggableLegend from '../components/DraggableLegend'
import { useKB } from '../contexts/KBContext'

function GraphPage() {
  const { currentKBId } = useKB()
  const [graph, setGraph] = useState<KnowledgeGraph>({ nodes: [], edges: [] })
  const [loading, setLoading] = useState(true)
  const [selectedNode, setSelectedNode] = useState<NodeDetail | null>(null)
  const [graphMode, setGraphMode] = useState<'2d' | '3d'>('2d')

  useEffect(() => {
    loadGraph()
  }, [currentKBId])

  // 监听全局 kb-changed 事件
  useEffect(() => {
    const handler = () => loadGraph()
    window.addEventListener('kb-changed', handler)
    return () => window.removeEventListener('kb-changed', handler)
  }, [currentKBId])

  // 切换到 3D 视图时，如果数据为空则重新加载
  useEffect(() => {
    if (graphMode === '3d' && graph.nodes.length === 0 && !loading) {
      loadGraph()
    }
  }, [graphMode])

  const loadGraph = async () => {
    setLoading(true)
    try {
      const res = await graphApi.getGraph(currentKBId)
      setGraph(res.data)
    } finally {
      setLoading(false)
    }
  }

  const handleNodeClick = async (node: GraphNode) => {
    try {
      const res = await graphApi.getNodeDetail(node.id)
      setSelectedNode(res.data)
    } catch {
      setSelectedNode(null)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 15 }}>
        <h2 style={{ margin: 0 }}>知识图谱</h2>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {/* 视图切换 */}
          <div style={{
            display: 'flex',
            gap: 5,
            background: '#f0f0f0',
            padding: 4,
            borderRadius: 8
          }}>
            <button
              onClick={() => setGraphMode('2d')}
              style={{
                padding: '6px 16px',
                border: 'none',
                borderRadius: 6,
                cursor: 'pointer',
                fontSize: 13,
                background: graphMode === '2d' ? '#2c3e50' : 'transparent',
                color: graphMode === '2d' ? '#fff' : '#666'
              }}
            >
              2D 视图
            </button>
            <button
              onClick={() => setGraphMode('3d')}
              style={{
                padding: '6px 16px',
                border: 'none',
                borderRadius: 6,
                cursor: 'pointer',
                fontSize: 13,
                background: graphMode === '3d' ? '#2c3e50' : 'transparent',
                color: graphMode === '3d' ? '#fff' : '#666'
              }}
            >
              3D 视图
            </button>
          </div>

          <button
            onClick={loadGraph}
            style={{
              padding: '8px 16px',
              background: '#2c3e50',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              cursor: 'pointer',
              fontSize: 14
            }}
          >
            刷新
          </button>
        </div>
      </div>

      <div style={{
        display: 'flex',
        gap: 15,
        alignItems: 'flex-start',
        height: 'calc(100vh - 180px)', // 限制整体高度，避免页面无意义滚动
        minHeight: 500
      }}>
        <div style={{
          flex: 1,
          height: '100%', // 撑满父容器高度
          border: '1px solid #eee',
          borderRadius: 12,
          overflow: 'hidden',
          background: '#f8f9fa',
          position: 'relative' // 为内部绝对定位提供基准
        }}>
          {loading ? (
            <div style={{ padding: 100, textAlign: 'center', color: '#999' }}>
              加载中...
            </div>
          ) : graph.nodes.length === 0 ? (
            <div style={{ padding: 100, textAlign: 'center', color: '#999' }}>
              <p>暂无知识图谱</p>
              <p style={{ fontSize: 14 }}>请先上传文档，系统会自动构建图谱</p>
            </div>
          ) : (
            <>
              {graphMode === '2d' ? (
                <Graph2D
                  data={graph}
                  onNodeClick={handleNodeClick}
                />
              ) : (
                <Graph3D
                  data={graph}
                  onNodeClick={handleNodeClick}
                />
              )}
              {/* v3: 可拖拽 + 边缘吸附 + 横竖自适应图例 */}
              <DraggableLegend graphMode={graphMode} />
            </>
          )}
        </div>

        <NodeDetailPanel
          detail={selectedNode}
          onClose={() => setSelectedNode(null)}
        />
      </div>
    </div>
  )
}

export default GraphPage
