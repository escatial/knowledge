/**
 * 知识图谱图例组件
 *
 * 集中维护"实体类型→颜色"的映射关系，与 Graph2D/Graph3D 的 getNodeColor 保持一致。
 * 任何节点类型的新增/修改只需在此处维护一次，前端图谱渲染、图例显示即同步更新。
 */
import { ReactNode } from 'react'

export interface LegendItem {
  type: string
  color: string
  description?: string
  category?: 'entity' | 'document' | 'relation'
}

export const NODE_COLOR_MAP: Record<string, string> = {
  '人物': '#e74c3c',
  '组织': '#3498db',
  '地点': '#2ecc71',
  '概念': '#9b59b6',
  '技术': '#f39c12',
  '产品': '#1abc9c',
  '事件': '#e67e22',
  '文档': '#34495e',
}

export const EDGE_COLOR_MAP: Record<string, string> = {
  '属于': '#7f8c8d',
  '包含': '#8e44ad',
  '关联': '#2980b9',
  '相关': '#27ae60',
  '提及': '#d35400',
  '引用': '#c0392b',
  '参与': '#16a085',
  '创建': '#2c3e50',
  '合作': '#f39c12',
  '位于': '#1abc9c',
  '工作于': '#e67e22',
  '学习': '#9b59b6',
  '研究': '#3498db',
}

export const NODE_LEGEND: LegendItem[] = [
  { type: '人物', color: '#e74c3c', description: '具体的人物个体（人名、角色等）', category: 'entity' },
  { type: '组织', color: '#3498db', description: '公司、机构、团队、社团等', category: 'entity' },
  { type: '地点', color: '#2ecc71', description: '地理位置、城市、建筑等', category: 'entity' },
  { type: '概念', color: '#9b59b6', description: '抽象概念、理论、思想', category: 'entity' },
  { type: '技术', color: '#f39c12', description: '技术、框架、语言、算法', category: 'entity' },
  { type: '产品', color: '#1abc9c', description: '产品、系统、应用、平台', category: 'entity' },
  { type: '事件', color: '#e67e22', description: '历史事件、动作、行为', category: 'entity' },
  { type: '文档', color: '#34495e', description: '文档源节点（仅文档类型节点会显示为该色）', category: 'document' },
]

export const EDGE_LEGEND: LegendItem[] = [
  { type: '属于', color: '#7f8c8d', description: '从属、归属关系' },
  { type: '包含', color: '#8e44ad', description: '包含、整体与部分' },
  { type: '关联', color: '#2980b9', description: '一般关联关系' },
  { type: '相关', color: '#27ae60', description: '相关性较强' },
  { type: '提及', color: '#d35400', description: '文本中提到、引用到' },
  { type: '引用', color: '#c0392b', description: '学术/资料引用' },
  { type: '参与', color: '#16a085', description: '参与、贡献' },
  { type: '合作', color: '#f39c12', description: '合作、共事' },
  { type: '位于', color: '#1abc9c', description: '地理/逻辑位置' },
  { type: '工作于', color: '#e67e22', description: '工作单位、组织' },
  { type: '研究', color: '#3498db', description: '研究方向' },
]

interface GraphLegendProps {
  /** 是否显示节点图例（默认 true） */
  showNodes?: boolean
  /** 是否显示关系图例（默认 true） */
  showEdges?: boolean
  /** 自定义节点图例数据（不传则用 NODE_LEGEND） */
  nodeItems?: LegendItem[]
  /** 自定义关系图例数据 */
  edgeItems?: LegendItem[]
  /** 紧凑模式（仅显示色块+名称） */
  compact?: boolean
  /** 标题 */
  title?: string
  /** 渲染方式：'inline' 内联一行；'grid' 多列网格；'section' 分区块 */
  layout?: 'inline' | 'grid' | 'section'
  /** 子节点（自定义内容时使用） */
  children?: ReactNode
}

/**
 * 获取节点类型对应的颜色（与 Graph2D/Graph3D 渲染逻辑保持同步）
 */
export function getNodeColor(type: string): string {
  return NODE_COLOR_MAP[type] || '#95a5a6'
}

/**
 * 获取边类型对应的颜色
 */
export function getEdgeColor(type: string): string {
  return EDGE_COLOR_MAP[type] || '#7f8c8d'
}

export function GraphLegend({
  showNodes = true,
  showEdges = true,
  nodeItems = NODE_LEGEND,
  edgeItems = EDGE_LEGEND,
  compact = false,
  title = '图例',
  layout = 'inline',
  children,
}: GraphLegendProps) {
  const renderSwatch = (item: LegendItem) => {
    if (item.category === 'document') {
      return (
        <span
          style={{
            display: 'inline-block',
            width: 16,
            height: 16,
            borderRadius: 4,
            background: item.color,
            flexShrink: 0,
          }}
        />
      )
    }
    return (
      <span
        style={{
          display: 'inline-block',
          width: 14,
          height: 14,
          borderRadius: '50%',
          background: item.color,
          flexShrink: 0,
        }}
      />
    )
  }

  const renderItem = (item: LegendItem) => {
    if (compact) {
      return (
        <div
          key={item.type}
          style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}
        >
          {renderSwatch(item)}
          <span>{item.type}</span>
        </div>
      )
    }
    return (
      <div
        key={item.type}
        title={item.description}
        style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}
      >
        {renderSwatch(item)}
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ fontWeight: 500, color: '#374151' }}>{item.type}</span>
          {item.description && (
            <span style={{ fontSize: 11, color: '#9ca3af' }}>{item.description}</span>
          )}
        </div>
      </div>
    )
  }

  if (children) {
    return <>{children}</>
  }

  if (layout === 'section') {
    return (
      <div
        style={{
          marginTop: 15,
          padding: 15,
          background: '#f8f9fa',
          borderRadius: 8,
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
        }}
      >
        <div style={{ fontWeight: 600, color: '#374151' }}>{title}</div>
        {showNodes && (
          <div>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              实体类型
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 8 }}>
              {nodeItems.map(renderItem)}
            </div>
          </div>
        )}
        {showEdges && edgeItems.length > 0 && (
          <div>
            <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              关系类型
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 8 }}>
              {edgeItems.map(renderItem)}
            </div>
          </div>
        )}
      </div>
    )
  }

  if (layout === 'grid') {
    return (
      <div
        style={{
          marginTop: 15,
          padding: 15,
          background: '#f8f9fa',
          borderRadius: 8,
        }}
      >
        <div style={{ fontWeight: 500, marginBottom: 8 }}>{title}：</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
          {showNodes && nodeItems.map(renderItem)}
          {showEdges && edgeItems.map((item, idx) => (
            <div
              key={`edge-${idx}`}
              style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}
            >
              <span
                style={{
                  display: 'inline-block',
                  width: 16,
                  height: 3,
                  background: item.color,
                  borderRadius: 1,
                  flexShrink: 0,
                }}
              />
              <span>{item.type}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  // inline layout
  return (
    <div
      style={{
        marginTop: 15,
        padding: 15,
        background: '#f8f9fa',
        borderRadius: 8,
        display: 'flex',
        gap: 16,
        flexWrap: 'wrap',
        alignItems: 'center',
      }}
    >
      <span style={{ fontWeight: 500 }}>{title}：</span>
      {showNodes && nodeItems.map(renderItem)}
      {showEdges && edgeItems.length > 0 && (
        <>
          <span style={{ width: 1, height: 16, background: '#e5e7eb' }}></span>
          {edgeItems.map((item) => (
            <div
              key={item.type}
              style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}
            >
              <span
                style={{
                  display: 'inline-block',
                  width: 16,
                  height: 3,
                  background: item.color,
                  borderRadius: 1,
                }}
              />
              <span>{item.type}</span>
            </div>
          ))}
        </>
      )}
    </div>
  )
}

export default GraphLegend
