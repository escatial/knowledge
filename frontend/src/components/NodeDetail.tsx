import { NodeDetail as NodeDetailType } from '../types'

interface NodeDetailProps {
  detail: NodeDetailType | null
  onClose: () => void
}

function NodeDetail({ detail, onClose }: NodeDetailProps) {
  if (!detail) return null

  const { node, edges, related_nodes } = detail

  return (
    <div style={{
      width: 350,
      flexShrink: 0, // 防止侧边栏被压缩
      height: '100%',
      overflow: 'auto',
      background: '#fff',
      border: '1px solid #e0e0e0',
      borderRadius: 12,
      padding: 20,
      boxShadow: '0 4px 20px rgba(0,0,0,0.05)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 15 }}>
        <h3 style={{ margin: 0, fontSize: 18 }}>{node.name}</h3>
        <button onClick={onClose} style={{ 
          border: 'none', 
          background: 'none', 
          fontSize: 20, 
          cursor: 'pointer',
          color: '#999'
        }}>×</button>
      </div>

      <div style={{ marginBottom: 15 }}>
        <span style={{
          display: 'inline-block',
          padding: '4px 12px',
          borderRadius: 20,
          background: getTypeColor(node.type),
          color: '#fff',
          fontSize: 12
        }}>
          {node.type}
        </span>
      </div>

      {node.description && (
        <p style={{ color: '#666', lineHeight: 1.6, marginBottom: 20 }}>
          {node.description}
        </p>
      )}

      <h4 style={{ borderBottom: '1px solid #eee', paddingBottom: 8 }}>
        关联关系 ({edges.length})
      </h4>

      <ul style={{ listStyle: 'none', padding: 0 }}>
        {edges.map((edge, idx) => {
          const isSource = edge.source === node.id
          const otherId = isSource ? edge.target : edge.source
          const otherNode = related_nodes.find(n => n.id === otherId)

          return (
            <li key={idx} style={{
              padding: '10px 0',
              borderBottom: '1px solid #f5f5f5',
              fontSize: 14
            }}>
              <span style={{ color: '#666' }}>
                {isSource ? '→' : '←'}
              </span>
              <span style={{ marginLeft: 8, fontWeight: 500 }}>
                {edge.type}
              </span>
              <span style={{ marginLeft: 8, color: '#3498db' }}>
                {otherNode?.name || otherId}
              </span>
              {edge.description && (
                <p style={{ margin: '4px 0 0 24px', color: '#999', fontSize: 12 }}>
                  {edge.description}
                </p>
              )}
            </li>
          )
        })}
      </ul>

      {related_nodes.length > 0 && (
        <>
          <h4 style={{ borderBottom: '1px solid #eee', paddingBottom: 8, marginTop: 20 }}>
            关联实体 ({related_nodes.length})
          </h4>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {related_nodes.map(n => (
              <span key={n.id} style={{
                padding: '4px 10px',
                borderRadius: 16,
                background: '#f0f0f0',
                fontSize: 12,
                color: '#555'
              }}>
                {n.name}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function getTypeColor(type: string): string {
  const colors: Record<string, string> = {
    '人物': '#e74c3c',
    '组织': '#3498db',
    '地点': '#2ecc71',
    '概念': '#9b59b6',
    '技术': '#f39c12',
    '产品': '#1abc9c',
    '事件': '#e67e22',
    '文档': '#34495e'
  }
  return colors[type] || '#95a5a6'
}

export default NodeDetail
