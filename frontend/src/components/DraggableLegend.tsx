import { useEffect, useRef, useState, useCallback } from 'react'
import { ChevronUp, ChevronDown, Move } from 'lucide-react'
import { NODE_LEGEND, EDGE_LEGEND } from './GraphLegend'

/**
 * 可拖拽 + 边缘吸附 + 横竖自适应布局的图例
 *
 *  - 顶部 title bar 拖拽手柄（Move 图标提示）
 *  - 拖到页面左半边 → 吸附左边缘，纵向布局（高 > 宽）
 *  - 拖到页面下半边 → 吸附下边缘，横向布局（宽 > 高）
 *  - 拖到右半边/上半边 → 维持当前位置（不吸附）
 *  - 折叠/展开按钮保留在标题栏
 */
export default function DraggableLegend({
  graphMode = '2d',
}: {
  graphMode?: '2d' | '3d'
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const dragStartRef = useRef<{ x: number; y: number; baseLeft: number; baseTop: number } | null>(null)
  // 拖拽位置：相对父容器的 left/top（px）。初始为「底部居中」吸附态。
  const [position, setPosition] = useState<{ left: number; top: number; snap: 'left' | 'bottom' | 'free' }>({
    left: 0,
    top: 0,
    snap: 'bottom',
  })
  const [collapsed, setCollapsed] = useState(false)

  // 拖拽开始：记录鼠标 + 图例基准位置
  const handleDragStart = (e: React.PointerEvent) => {
    if (!containerRef.current) return
    const parentRect = containerRef.current.parentElement?.getBoundingClientRect()
    if (!parentRect) return
    containerRef.current.setPointerCapture(e.pointerId)
    dragStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      baseLeft: position.left,
      baseTop: position.top,
    }
  }

  // 拖拽中
  const handleDragMove = useCallback((e: PointerEvent) => {
    if (!dragStartRef.current || !containerRef.current) return
    const parentRect = containerRef.current.parentElement?.getBoundingClientRect()
    if (!parentRect) return
    const dx = e.clientX - dragStartRef.current.x
    const dy = e.clientY - dragStartRef.current.y
    setPosition({
      left: dragStartRef.current.baseLeft + dx,
      top: dragStartRef.current.baseTop + dy,
      snap: 'free',
    })
  }, [])

  // 拖拽结束：边缘吸附
  const handleDragEnd = useCallback((e: PointerEvent) => {
    if (!containerRef.current) return
    containerRef.current.releasePointerCapture?.(e.pointerId)
    dragStartRef.current = null
    if (!containerRef.current.parentElement) return
    const rect = containerRef.current.getBoundingClientRect()
    const parentRect = containerRef.current.parentElement.getBoundingClientRect()
    // 图例中心相对父容器的归一化坐标 (0~1)
    const cx = (rect.left - parentRect.left + rect.width / 2) / parentRect.width
    const cy = (rect.top - parentRect.top + rect.height / 2) / parentRect.height

    // 左半区 → 吸附左边缘；下半区 → 吸附下边缘
    if (cx < 0.5) {
      setPosition({ left: 12, top: position.top, snap: 'left' })
    } else if (cy > 0.5) {
      setPosition({ left: position.left, top: parentRect.height - rect.height - 12, snap: 'bottom' })
    }
    // 其他位置保持
  }, [position.top])

  // 注册全局监听（仅在拖拽中）
  useEffect(() => {
    const onMove = (e: PointerEvent) => handleDragMove(e)
    const onUp = (e: PointerEvent) => handleDragEnd(e)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
    }
  }, [handleDragMove, handleDragEnd])

  // 容器样式：左吸附 → 纵向布局（高>宽）；下吸附 → 横向布局
  const isVertical = position.snap === 'left'
  // 任务 5.1：横向布局时宽度自适应主屏（左右各留 24px 留白），用 calc(100% - 48px)
  // 任务 5.2：transition 应用于 left/top/bottom/width — 让吸附/宽度变化平滑
  const containerStyle: React.CSSProperties = {
    position: 'absolute',
    left: position.snap === 'left' ? `${position.left}px` : position.snap === 'bottom' ? '50%' : `${position.left}px`,
    top: position.snap === 'left' || position.snap === 'free' ? `${position.top}px` : 'auto',
    bottom: position.snap === 'bottom' ? '12px' : 'auto',
    transform: position.snap === 'bottom' ? 'translateX(-50%)' : undefined,
    zIndex: 20,
    width: isVertical ? '180px' : 'calc(100% - 48px)',
    maxWidth: isVertical ? '180px' : 'calc(100% - 48px)',
    maxHeight: '85%',
    userSelect: 'none',
    touchAction: 'none',
    transition: 'left 250ms ease, top 250ms ease, bottom 250ms ease, width 250ms ease',
  }

  const panelStyle: React.CSSProperties = {
    background: 'rgba(255,255,255,0.95)',
    backdropFilter: 'blur(8px)',
    borderRadius: 12,
    border: '1px solid rgba(0,0,0,0.08)',
    boxShadow: '0 4px 16px rgba(0,0,0,0.1)',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: isVertical ? 'column' : 'column',
    width: isVertical ? 180 : '100%',
    minWidth: isVertical ? 180 : 0,
    transition: 'width 250ms ease',
  }

  return (
    <div ref={containerRef} style={containerStyle} data-testid="draggable-legend">
      <div style={panelStyle}>
        {/* 拖拽手柄 + 标题栏 */}
        <div
          onPointerDown={handleDragStart}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 12px',
            cursor: 'grab',
            background: 'rgba(0,0,0,0.02)',
            borderBottom: collapsed ? 'none' : '1px solid rgba(0,0,0,0.05)',
            userSelect: 'none',
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color: '#374151' }}>
            <Move className="h-3 w-3 text-gray-400" />
            图例说明
          </span>
          <span
            onClick={(e) => { e.stopPropagation(); setCollapsed(!collapsed) }}
            style={{
              display: 'flex', alignItems: 'center', gap: 4, fontSize: 10,
              color: '#9ca3af', cursor: 'pointer', padding: '2px 6px', borderRadius: 4,
            }}
          >
            点击{collapsed ? '展开' : '收起'}
            {collapsed ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </span>
        </div>
        {!collapsed && (
          <div
            style={{
              padding: '10px 14px 12px',
              display: 'flex',
              flexDirection: isVertical ? 'column' : 'row',
              gap: isVertical ? 12 : 24,
              maxHeight: isVertical ? 'calc(100vh - 200px)' : 240,
              overflowY: isVertical ? 'auto' : 'hidden',
              overflowX: isVertical ? 'hidden' : 'auto',
            }}
          >
            {/* 实体类型 */}
            <div style={{ flex: isVertical ? '0 0 auto' : '0 0 auto', minWidth: isVertical ? 'auto' : 220 }}>
              <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 6, fontWeight: 500 }}>
                实体类型
              </div>
              <div
                style={{
                  display: 'flex',
                  flexDirection: isVertical ? 'column' : 'row',
                  flexWrap: isVertical ? 'nowrap' : 'wrap',
                  gap: isVertical ? 5 : 8,
                }}
              >
                {NODE_LEGEND.map((item) => (
                  <div
                    key={item.type}
                    title={item.description}
                    style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, whiteSpace: 'nowrap' }}
                  >
                    <span
                      style={{
                        display: 'inline-block',
                        width: item.category === 'document' ? 12 : 10,
                        height: item.category === 'document' ? 12 : 10,
                        borderRadius: item.category === 'document' ? 3 : '50%',
                        background: item.color,
                        flexShrink: 0,
                        border: '1px solid rgba(0,0,0,0.1)',
                      }}
                    />
                    <span style={{ color: '#4b5563' }}>{item.type}</span>
                  </div>
                ))}
              </div>
            </div>
            {/* 关系类型（仅 2D） */}
            {graphMode === '2d' && (
              <div style={{ flex: '0 0 auto', minWidth: isVertical ? 'auto' : 240 }}>
                <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 6, fontWeight: 500 }}>
                  关系类型
                </div>
                <div
                  style={{
                    display: 'flex',
                    flexDirection: isVertical ? 'column' : 'row',
                    flexWrap: isVertical ? 'nowrap' : 'wrap',
                    gap: isVertical ? 5 : 8,
                  }}
                >
                  {EDGE_LEGEND.map((item) => (
                    <div
                      key={item.type}
                      title={item.description}
                      style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, whiteSpace: 'nowrap' }}
                    >
                      <span
                        style={{
                          display: 'inline-block',
                          width: 16,
                          height: 2,
                          background: item.color,
                          borderRadius: 1,
                          flexShrink: 0,
                        }}
                      />
                      <span style={{ color: '#4b5563' }}>{item.type}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
