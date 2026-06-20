import { useEffect, useRef, useCallback, useState } from 'react'
import { KnowledgeGraph, GraphNode } from '../types'
import { getNodeColor, getEdgeColor } from './GraphLegend'

interface Graph2DProps {
  data?: KnowledgeGraph
  onNodeClick?: (node: GraphNode) => void
}

function Graph2D({ data, onNodeClick }: Graph2DProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animationRef = useRef<number>(0)
  const nodesRef = useRef<any[]>([])
  const edgesRef = useRef<any[]>([])
  const isRunningRef = useRef(true)
  const alphaRef = useRef(1.0) // 引入冷却系数
  const frameCountRef = useRef(0)
  
  // 尺寸
  const dimensionsRef = useRef({ width: 900, height: 650 })
  
  // 视图变换
  const transformRef = useRef({ x: 0, y: 0, scale: 1 })
  const isPanningRef = useRef(false)
  const lastMousePosRef = useRef({ x: 0, y: 0 })
  const needsRenderRef = useRef(true)
  
  // 拖拽和选中状态
  const [isDragging, setIsDragging] = useState(false)
  const dragNodeRef = useRef<any | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  // 关键：用 ref 镜像 state，让 render 闭包（持有 useEffect 旧引用）能读到最新值
  const hoveredNodeIdRef = useRef<string | null>(null)
  const selectedNodeIdRef = useRef<string | null>(null)
  useEffect(() => { hoveredNodeIdRef.current = hoveredNodeId }, [hoveredNodeId])
  useEffect(() => { selectedNodeIdRef.current = selectedNodeId }, [selectedNodeId])

  const getWorldCoords = (clientX: number, clientY: number, rect: DOMRect) => {
    const { x, y, scale } = transformRef.current
    return {
      wx: (clientX - rect.left - x) / scale,
      wy: (clientY - rect.top - y) / scale
    }
  }

  const handleMouseDown = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return

    const rect = canvas.getBoundingClientRect()
    const { wx, wy } = getWorldCoords(e.clientX, e.clientY, rect)

    // 查找点击的节点
    let clickedNode = null
    for (let i = nodesRef.current.length - 1; i >= 0; i--) {
      const node = nodesRef.current[i]
      const dx = wx - node.x
      const dy = wy - node.y
      if (Math.sqrt(dx * dx + dy * dy) < node.radius) {
        clickedNode = node
        break
      }
    }

    if (clickedNode) {
      if (onNodeClick) onNodeClick(clickedNode)
      setSelectedNodeId(clickedNode.id)
      setIsDragging(true)
      dragNodeRef.current = clickedNode
      clickedNode.isDragging = true
      needsRenderRef.current = true
    } else {
      setSelectedNodeId(null)
      isPanningRef.current = true
      lastMousePosRef.current = { x: e.clientX, y: e.clientY }
      needsRenderRef.current = true
    }
  }, [onNodeClick])

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (isDragging && dragNodeRef.current) {
      const canvas = canvasRef.current
      if (!canvas) return
      const rect = canvas.getBoundingClientRect()
      const { wx, wy } = getWorldCoords(e.clientX, e.clientY, rect)

      dragNodeRef.current.x = wx
      dragNodeRef.current.y = wy
      dragNodeRef.current.vx = 0
      dragNodeRef.current.vy = 0
      needsRenderRef.current = true
      isRunningRef.current = true // 唤醒物理引擎
      alphaRef.current = 0.3 // 拖拽时保持一定的热量
    } else if (isPanningRef.current) {
      const dx = e.clientX - lastMousePosRef.current.x
      const dy = e.clientY - lastMousePosRef.current.y
      transformRef.current.x += dx
      transformRef.current.y += dy
      lastMousePosRef.current = { x: e.clientX, y: e.clientY }
      needsRenderRef.current = true
    } else {
      // v3: 悬停检测 —— 鼠标悬浮时自动高亮及关联实体
      const canvas = canvasRef.current
      if (!canvas) return
      const rect = canvas.getBoundingClientRect()
      const { wx, wy } = getWorldCoords(e.clientX, e.clientY, rect)
      let found = false
      for (let i = nodesRef.current.length - 1; i >= 0; i--) {
        const node = nodesRef.current[i]
        const dx = wx - node.x
        const dy = wy - node.y
        if (Math.sqrt(dx * dx + dy * dy) < node.radius + 5) {
          if (hoveredNodeIdRef.current !== node.id) {
            hoveredNodeIdRef.current = node.id
            setHoveredNodeId(node.id)
            needsRenderRef.current = true
          }
          found = true
          break
        }
      }
      if (!found && hoveredNodeIdRef.current !== null) {
        hoveredNodeIdRef.current = null
        setHoveredNodeId(null)
        needsRenderRef.current = true
      }
    }
  }, [isDragging, hoveredNodeId])

  const handleMouseUp = useCallback(() => {
    if (dragNodeRef.current) {
      dragNodeRef.current.isDragging = false
      dragNodeRef.current.dragReleaseFrames = 30 // 释放冷却帧数
    }
    setIsDragging(false)
    dragNodeRef.current = null
    isPanningRef.current = false
  }, [])

  const handleMouseLeave = useCallback(() => {
    if (dragNodeRef.current) {
      dragNodeRef.current.isDragging = false
      dragNodeRef.current.dragReleaseFrames = 30
    }
    setIsDragging(false)
    dragNodeRef.current = null
    isPanningRef.current = false
  }, [])

  const handleWheel = useCallback((e: WheelEvent) => {
    e.preventDefault()
    const canvas = canvasRef.current
    if (!canvas) return

    const rect = canvas.getBoundingClientRect()
    const mouseX = e.clientX - rect.left
    const mouseY = e.clientY - rect.top

    const zoomSensitivity = 0.001
    const delta = -e.deltaY * zoomSensitivity
    const newScale = Math.min(Math.max(0.1, transformRef.current.scale * (1 + delta)), 5)

    const scaleRatio = newScale / transformRef.current.scale
    transformRef.current.x = mouseX - (mouseX - transformRef.current.x) * scaleRatio
    transformRef.current.y = mouseY - (mouseY - transformRef.current.y) * scaleRatio
    transformRef.current.scale = newScale

    needsRenderRef.current = true
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (canvas) {
      canvas.addEventListener('wheel', handleWheel, { passive: false })
      return () => canvas.removeEventListener('wheel', handleWheel)
    }
  }, [handleWheel])

  // 如果没有数据，使用空数据
  const graphData = data || { nodes: [], edges: [] }

  useEffect(() => {
    if (!containerRef.current) return
    const resizeObserver = new ResizeObserver(entries => {
      for (let entry of entries) {
        const { width, height } = entry.contentRect
        if (width === 0 || height === 0) continue
        dimensionsRef.current = { width, height }
        if (canvasRef.current) {
          canvasRef.current.width = width
          canvasRef.current.height = height
          needsRenderRef.current = true
        }
      }
    })
    resizeObserver.observe(containerRef.current)
    return () => resizeObserver.disconnect()
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || graphData.nodes.length === 0) return

    const { width, height } = dimensionsRef.current
    // 启用硬件加速上下文
    const ctx = canvas.getContext('2d', { alpha: false })!
    canvas.width = width
    canvas.height = height
    isRunningRef.current = true
    alphaRef.current = 1.0 // 重置温度
    needsRenderRef.current = true
    frameCountRef.current = 0

    // 限制最大节点数
    const maxNodes = 400
    let displayNodes = graphData.nodes
    if (graphData.nodes.length > maxNodes) {
      const typeGroups: Record<string, GraphNode[]> = {}
      graphData.nodes.forEach(n => {
        if (!typeGroups[n.type]) typeGroups[n.type] = []
        typeGroups[n.type].push(n)
      })
      
      displayNodes = []
      const types = Object.keys(typeGroups)
      const perType = Math.floor(maxNodes / types.length)
      types.forEach(type => {
        displayNodes.push(...typeGroups[type].slice(0, perType))
      })
    }

    const nodeIdSet = new Set(displayNodes.map(n => n.id))

    const centerX = dimensionsRef.current.width / 2
    const centerY = dimensionsRef.current.height / 2
    const nodeMap = new Map<string, any>()

    // 按类型分组
    const typeGroups: Record<string, GraphNode[]> = {}
    displayNodes.forEach(n => {
      if (!typeGroups[n.type]) typeGroups[n.type] = []
      typeGroups[n.type].push(n)
    })

    const typeKeys = Object.keys(typeGroups)
    const typeAngleStep = (Math.PI * 2) / Math.max(typeKeys.length, 1)

    nodesRef.current = displayNodes.map((n) => {
      const typeIndex = typeKeys.indexOf(n.type)
      const groupSize = typeGroups[n.type].length
      const groupIndex = typeGroups[n.type].indexOf(n)

      const baseAngle = typeIndex * typeAngleStep
      const groupOffset = (groupIndex / Math.max(groupSize, 1)) * (typeAngleStep * 0.6) - (typeAngleStep * 0.3)
      const angle = baseAngle + groupOffset + Math.random() * 0.1

      const radius = 120 + Math.random() * 80
      const node = {
        ...n,
        x: centerX + Math.cos(angle) * radius,
        y: centerY + Math.sin(angle) * radius,
        radius: n.category === 'document' ? 18 : 10,
        color: getNodeColor(n.type),
        vx: 0,
        vy: 0,
        isDragging: false,
        isSelected: n.id === selectedNodeId,
        dragReleaseFrames: 0,
      }
      nodeMap.set(n.id, node)
      return node
    })

    edgesRef.current = graphData.edges
      .filter(e => nodeIdSet.has(e.source) && nodeIdSet.has(e.target))
      .map(e => ({
        source: nodeMap.get(e.source),
        target: nodeMap.get(e.target),
        type: e.type
      })).filter(e => e.source && e.target)

    let lastTime = performance.now()
    
    const simulate = () => {
      if (!isRunningRef.current) return false
      
      const now = performance.now()
      // 固定最大时间步长，避免因为掉帧导致的 dt 暴增引起坐标爆炸（抖动根源）
      const dt = Math.min((now - lastTime) / 16.67, 1.5)
      lastTime = now
      
      frameCountRef.current++

      // 冷却降温
      alphaRef.current *= 0.98
      const alpha = alphaRef.current

      // 当温度足够低时，完全停止物理计算
      if (alpha < 0.005) {
        isRunningRef.current = false
        return false
      }

      let totalEnergy = 0

      if (frameCountRef.current % 1 === 0) { // 每一帧都更新物理，避免跳帧带来的突变
        const nodes = nodesRef.current
        const edges = edgesRef.current
        const k = 100 // 基础弹簧长度
        const repulsion = 4000 // 斥力系数
        const maxDist = 300 // 斥力最大作用距离

        for (let i = 0; i < nodes.length; i++) {
          const nodeA = nodes[i]
          if (nodeA.isDragging) continue

          for (let j = i + 1; j < nodes.length; j++) {
            const nodeB = nodes[j]
            if (nodeB.isDragging) continue

            const dx = nodeB.x - nodeA.x
            const dy = nodeB.y - nodeA.y
            const distSq = dx * dx + dy * dy
            if (distSq < maxDist * maxDist && distSq > 0.1) {
              const dist = Math.sqrt(distSq)
              const force = (repulsion / distSq) * alpha // 力随温度衰减
              const fx = (dx / dist) * force
              const fy = (dy / dist) * force
              nodeA.vx -= fx
              nodeA.vy -= fy
              nodeB.vx += fx
              nodeB.vy += fy
            }
          }
        }

        for (const edge of edges) {
          if (edge.source.isDragging || edge.target.isDragging) continue

          const dx = edge.target.x - edge.source.x
          const dy = edge.target.y - edge.source.y
          const dist = Math.sqrt(dx * dx + dy * dy) || 0.1
          const force = (dist - k) * 0.02 * alpha // 弹簧力也随温度衰减
          const fx = (dx / dist) * force
          const fy = (dy / dist) * force
          edge.source.vx += fx
          edge.source.vy += fy
          edge.target.vx -= fx
          edge.target.vy -= fy
        }

        for (const node of nodes) {
          if (node.isDragging) continue

          const centerX = dimensionsRef.current.width / 2
          const centerY = dimensionsRef.current.height / 2

          // 释放冷却期：减弱中心引力让节点停留在用户放置的位置
          const releaseFactor = node.dragReleaseFrames > 0
            ? Math.max(0.05, node.dragReleaseFrames / 30)
            : 1.0

          if (node.dragReleaseFrames > 0) {
            node.dragReleaseFrames--
          }

          // 中心引力（释放冷却期大幅减弱）
          const dx = centerX - node.x
          const dy = centerY - node.y
          node.vx += dx * 0.0005 * alpha * releaseFactor
          node.vy += dy * 0.0005 * alpha * releaseFactor

          // 限制最大速度，避免坐标爆炸飞出
          const speedSq = node.vx * node.vx + node.vy * node.vy
          if (speedSq > 100) {
            const speed = Math.sqrt(speedSq)
            node.vx = (node.vx / speed) * 10
            node.vy = (node.vy / speed) * 10
          }

          // 摩擦力
          node.vx *= 0.8
          node.vy *= 0.8
          
          node.x += node.vx * dt
          node.y += node.vy * dt
          
          totalEnergy += node.vx * node.vx + node.vy * node.vy
        }
      }
      return true
    }

    const render = () => {
      const didSimulate = simulate()
      
      // 只有在需要渲染时才重绘
      if (didSimulate || needsRenderRef.current) {
        needsRenderRef.current = false
        
        ctx.fillStyle = '#f8f9fa' // 使用实色填充背景以优化性能
        ctx.fillRect(0, 0, dimensionsRef.current.width, dimensionsRef.current.height)

        const { x, y, scale } = transformRef.current
        
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(scale, scale)

        // 视口剔除 (Viewport Culling)
        const viewMinX = -x / scale
        const viewMinY = -y / scale
        const viewMaxX = (dimensionsRef.current.width - x) / scale
        const viewMaxY = (dimensionsRef.current.height - y) / scale
        const margin = 50 // 容差

        // 筛选可见节点
        const visibleNodes = new Set()
        for (const node of nodesRef.current) {
          if (
            node.x + node.radius + margin >= viewMinX &&
            node.x - node.radius - margin <= viewMaxX &&
            node.y + node.radius + margin >= viewMinY &&
            node.y - node.radius - margin <= viewMaxY
          ) {
            visibleNodes.add(node)
          }
        }

        // 构建选中节点（或悬停节点）的关联集合 —— 用 ref 镜像 state，避开 useEffect 闭包陷阱
        const activeNodeId = hoveredNodeIdRef.current || selectedNodeIdRef.current
        const connectedIds = new Set<string>()
        if (activeNodeId) {
          for (const edge of edgesRef.current) {
            const srcId = edge.source.id || edge.source
            const tgtId = edge.target.id || edge.target
            if (srcId === activeNodeId) connectedIds.add(tgtId)
            if (tgtId === activeNodeId) connectedIds.add(srcId)
          }
        }

        // 批量绘制边 (先画非高亮边，再画高亮边)
        ctx.lineWidth = 1 / scale
        // 普通边
        ctx.strokeStyle = 'rgba(189, 195, 199, 0.25)'
        ctx.beginPath()
        const highlightEdges: typeof edgesRef.current = []
        for (const edge of edgesRef.current) {
          if (!visibleNodes.has(edge.source) && !visibleNodes.has(edge.target)) continue
          const srcId = edge.source.id || edge.source
          const tgtId = edge.target.id || edge.target
          if (activeNodeId && (srcId === activeNodeId || tgtId === activeNodeId)) {
            highlightEdges.push(edge)
            continue
          }
          ctx.moveTo(edge.source.x, edge.source.y)
          ctx.lineTo(edge.target.x, edge.target.y)
        }
        ctx.stroke()

        // 高亮边（关联选中/悬停节点的边，加粗+颜色）
        for (const edge of highlightEdges) {
          const edgeType = edge.type || '关联'
          const isFromSelected = (edge.source.id || edge.source) === activeNodeId

          // 绘制连接线
          ctx.beginPath()
          ctx.moveTo(edge.source.x, edge.source.y)
          ctx.lineTo(edge.target.x, edge.target.y)
          ctx.strokeStyle = getEdgeColor(edgeType)
          ctx.lineWidth = 2.5 / scale
          ctx.stroke()

          // 绘制箭头（从选中节点出发的边）
          if (isFromSelected) {
            drawArrow(ctx, edge.source.x, edge.source.y, edge.target.x, edge.target.y, getEdgeColor(edgeType), scale)
          }

          // 绘制边标签
          const midX = (edge.source.x + edge.target.x) / 2
          const midY = (edge.source.y + edge.target.y) / 2
          const offset = 12 / scale
          // 计算法线方向偏移避免标签与线重叠
          const dx = edge.target.x - edge.source.x
          const dy = edge.target.y - edge.source.y
          const len = Math.sqrt(dx * dx + dy * dy) || 1
          const nx = -dy / len * offset
          const ny = dx / len * offset

          ctx.font = `${11 / scale}px sans-serif`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          const textWidth = ctx.measureText(edgeType).width // 必须在 fillText 之前获取
          const labelX = midX + nx
          const labelY = midY + ny

          // 标签背景
          const bgPad = 3 / scale
          ctx.fillStyle = 'rgba(255,255,255,0.85)'
          ctx.fillRect(
            labelX - textWidth / 2 - bgPad,
            labelY - 7 / scale - bgPad,
            textWidth + bgPad * 2,
            14 / scale + bgPad * 2
          )
          // 标签文字
          ctx.fillStyle = getEdgeColor(edgeType)
          ctx.fillText(edgeType, labelX, labelY)
        }

        // 批量绘制节点
        for (const node of nodesRef.current) {
          if (!visibleNodes.has(node)) continue

          const isSelected = node.id === selectedNodeIdRef.current
          const isHovered = node.id === hoveredNodeIdRef.current && !isSelected
          const isConnected = connectedIds.has(node.id)
          // 有激活节点时，非关联节点降低透明度（悬停也适用）
          const targetAlpha = (activeNodeId && !isSelected && !isHovered && !isConnected) ? 0.25 : 1.0
          // 任务 5.2：平滑过渡 alpha（每帧朝目标插值 15%）—— 消除生硬切换
          if (typeof node.currentAlpha !== 'number') node.currentAlpha = 1.0
          node.currentAlpha += (targetAlpha - node.currentAlpha) * 0.15
          const dimAlpha = node.currentAlpha

          if (isSelected || isHovered) {
            // 选中/悬停节点外发光
            ctx.beginPath()
            ctx.arc(node.x, node.y, node.radius + 10, 0, Math.PI * 2)
            ctx.fillStyle = `${node.color}22`
            ctx.fill()
            // 脉冲环
            ctx.beginPath()
            ctx.arc(node.x, node.y, node.radius + 6, 0, Math.PI * 2)
            ctx.strokeStyle = `${node.color}66`
            ctx.lineWidth = 2 / scale
            ctx.stroke()
          } else if (isConnected) {
            // 关联节点发光
            ctx.beginPath()
            ctx.arc(node.x, node.y, node.radius + 5, 0, Math.PI * 2)
            ctx.fillStyle = `${node.color}15`
            ctx.fill()
          }

          ctx.beginPath()
          const displayRadius = isSelected ? node.radius * 1.6 : (isHovered ? node.radius * 1.4 : (isConnected ? node.radius * 1.2 : node.radius))
          ctx.arc(node.x, node.y, displayRadius, 0, Math.PI * 2)
          ctx.globalAlpha = dimAlpha
          ctx.fillStyle = node.color
          ctx.fill()
          ctx.globalAlpha = 1.0
          
          if (isSelected) {
            ctx.strokeStyle = '#ff6b6b'
            ctx.lineWidth = 3 / scale
          } else if (isHovered) {
            ctx.strokeStyle = '#3498db'
            ctx.lineWidth = 2.5 / scale
          } else if (isConnected) {
            ctx.strokeStyle = node.color
            ctx.lineWidth = 2 / scale
          } else if (node.isDragging) {
            ctx.strokeStyle = '#ff9f43'
            ctx.lineWidth = 3 / scale
          } else {
            ctx.strokeStyle = 'rgba(255,255,255,0.8)'
            ctx.lineWidth = 1.5 / scale
          }
          ctx.globalAlpha = dimAlpha
          ctx.stroke()
          ctx.globalAlpha = 1.0

          // 根据缩放级别决定是否显示文字
          if (scale > 0.5 || isSelected || isConnected) {
            ctx.fillStyle = isSelected ? '#2c3e50' : '#555'
            ctx.font = isSelected
              ? `bold ${14/scale}px sans-serif`
              : isConnected
              ? `${12/scale}px sans-serif`
              : `${10/scale}px sans-serif`
            ctx.textAlign = 'center'
            ctx.textBaseline = 'top'
            const maxLen = isSelected ? 12 : (isConnected ? 10 : 6)
            const label = node.name.length > maxLen ? node.name.substring(0, maxLen) + '...' : node.name
            ctx.fillText(label, node.x, node.y + displayRadius + 8/scale)
          }
        }
        ctx.restore()
      }

      animationRef.current = requestAnimationFrame(render)
    }

    render()

    return () => {
      isRunningRef.current = false
      cancelAnimationFrame(animationRef.current)
    }
  }, [graphData])

  if (graphData.nodes.length === 0) {
    return (
      <div ref={containerRef} style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f8f9fa' }}>
        <p className="text-gray-400">暂无图谱数据</p>
      </div>
    )
  }

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', position: 'relative' }}>
      <canvas
        ref={canvasRef}
        style={{
          width: '100%',
          height: '100%',
          cursor: isDragging ? 'grabbing' : isPanningRef.current ? 'grabbing' : 'grab',
          display: 'block',
          touchAction: 'none' // 禁用浏览器默认的触摸缩放
        }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
      />
    </div>
  )
}

function drawArrow(
  ctx: CanvasRenderingContext2D,
  fromX: number, fromY: number,
  toX: number, toY: number,
  color: string,
  scale: number
) {
  const dx = toX - fromX
  const dy = toY - fromY
  const len = Math.sqrt(dx * dx + dy * dy)
  if (len < 20) return

  // 单位方向向量
  const ux = dx / len
  const uy = dy / len

  // 箭头尖端在目标节点边缘
  const arrowSize = 8 / scale
  const tipX = toX - ux * 26
  const tipY = toY - uy * 26

  // 箭头的两个后角
  const angle = Math.PI / 6 // 30度
  const leftX = tipX - arrowSize * Math.cos(Math.atan2(uy, ux) - angle)
  const leftY = tipY - arrowSize * Math.sin(Math.atan2(uy, ux) - angle)
  const rightX = tipX - arrowSize * Math.cos(Math.atan2(uy, ux) + angle)
  const rightY = tipY - arrowSize * Math.sin(Math.atan2(uy, ux) + angle)

  ctx.beginPath()
  ctx.moveTo(tipX, tipY)
  ctx.lineTo(leftX, leftY)
  ctx.lineTo(rightX, rightY)
  ctx.closePath()
  ctx.fillStyle = color
  ctx.fill()
}

export default Graph2D
