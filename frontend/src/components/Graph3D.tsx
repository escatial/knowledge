import { useEffect, useRef, useCallback, useState } from 'react'
import { KnowledgeGraph, GraphNode } from '../types'
import { NODE_COLOR_MAP } from './GraphLegend'

interface Graph3DProps {
  data?: KnowledgeGraph
  onNodeClick?: (node: GraphNode) => void
}

function Graph3D({ data, onNodeClick }: Graph3DProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const rendererRef = useRef<any>(null)
  const cameraRef = useRef<any>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  const handleClick = useCallback((node: any) => {
    if (onNodeClick && node) {
      onNodeClick(node as GraphNode)
    }
    setSelectedNodeId(node.id)
  }, [onNodeClick])

  // 处理窗口或容器尺寸变化
  useEffect(() => {
    if (!containerRef.current) return
    
    const resizeObserver = new ResizeObserver(entries => {
      for (let entry of entries) {
        const { width, height } = entry.contentRect
        if (width === 0 || height === 0) continue
        
        if (rendererRef.current && cameraRef.current) {
          rendererRef.current.setSize(width, height)
          cameraRef.current.aspect = width / height
          cameraRef.current.updateProjectionMatrix()
        }
      }
    })
    
    resizeObserver.observe(containerRef.current)
    return () => resizeObserver.disconnect()
  }, [])

  // 如果没有数据，使用空数据
  const graphData = data || { nodes: [], edges: [] }

  useEffect(() => {
    if (!containerRef.current) return

    let scene: any, camera: any, renderer: any, animationId: number
    let isActive = true
    const { clientWidth, clientHeight } = containerRef.current
    const width = clientWidth || 900
    const height = clientHeight || 650

    const init = async () => {
      try {
        // 动态导入 THREE 库及 OrbitControls
        const THREE = await import('three')
        const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js')

        // 清空容器
        if (containerRef.current) {
          containerRef.current.innerHTML = ''
        }

        // 等待数据加载完成（如果数据正在加载中）
        if (graphData.nodes.length === 0) {
          setIsLoading(false)
          // 仍然初始化空场景，以便后续数据更新时可以直接渲染
        }

        // 场景
        scene = new THREE.Scene()
        scene.background = new THREE.Color(0xf8f9fa)

        // 相机
        camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 1000)
        camera.position.z = 150
        cameraRef.current = camera

        // 渲染器 - 降低像素比提升性能
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
        renderer.setSize(width, height)
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5))
        containerRef.current!.appendChild(renderer.domElement)
        rendererRef.current = renderer

        // 鼠标交互控制 (OrbitControls)
        const controls = new OrbitControls(camera, renderer.domElement)
        controls.enableDamping = true
        controls.dampingFactor = 0.05
        controls.minDistance = 20
        controls.maxDistance = 500
        controls.autoRotate = true
        controls.autoRotateSpeed = 0.5
        // 限制视角避免失控
        controls.maxPolarAngle = Math.PI

        // 添加光照优化
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.7)
        scene.add(ambientLight)
        
        const directionalLight = new THREE.DirectionalLight(0xffffff, 0.6)
        directionalLight.position.set(20, 30, 20)
        scene.add(directionalLight)
        
        const backLight = new THREE.DirectionalLight(0xffffff, 0.3)
        backLight.position.set(-20, -30, -20)
        scene.add(backLight)

        if (graphData.nodes.length === 0) {
          setIsLoading(false)
          animate()
          return
        }

        // 限制最大节点数，优先保留重要节点
        const maxNodes = 300
        let displayNodes = graphData.nodes
        if (graphData.nodes.length > maxNodes) {
          // 按类型分组，每组保留一定数量的节点
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

        // 节点分组
        const typeGroups: Record<string, GraphNode[]> = {}
        displayNodes.forEach(n => {
          if (!typeGroups[n.type]) typeGroups[n.type] = []
          typeGroups[n.type].push(n)
        })

        const typeKeys = Object.keys(typeGroups)
        const typeAngleStep = (Math.PI * 2) / Math.max(typeKeys.length, 1)

        // 创建节点 - 使用共享几何体和材质
        const nodeMeshes: any[] = []
        const nodeMap = new Map<string, any>()
        const textSprites: any[] = []
        
        // 预创建几何体 (降低分段数以优化性能)
        const largeGeo = new THREE.SphereGeometry(4, 12, 12)
        const smallGeo = new THREE.SphereGeometry(2.5, 8, 8)
        const selectedGeo = new THREE.SphereGeometry(6, 16, 16)
        
        // 预创建材质缓存
        const materialCache = new Map<number, any>()
        const getMaterial = (color: number, isSelected: boolean = false) => {
          const key = isSelected ? color + 1 : color
          if (!materialCache.has(key)) {
            const material = new THREE.MeshPhongMaterial({ 
              color: isSelected ? new THREE.Color(color).multiplyScalar(1.3) : color,
              shininess: isSelected ? 100 : 30,
              emissive: isSelected ? new THREE.Color(color).multiplyScalar(0.2) : 0x000000
            })
            materialCache.set(key, material)
          }
          return materialCache.get(key)
        }

        // 创建文字精灵
        const createTextSprite = (text: string) => {
          const canvas = document.createElement('canvas')
          const ctx = canvas.getContext('2d')
          if (!ctx) return null
          
          const fontSize = 24
          canvas.width = 256
          canvas.height = 128
          
          ctx.fillStyle = 'rgba(255,255,255,0)'
          ctx.fillRect(0, 0, canvas.width, canvas.height)
          
          ctx.font = `bold ${fontSize}px sans-serif`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillStyle = '#333333'
          
          const displayText = text.length > 8 ? text.substring(0, 8) + '...' : text
          ctx.fillText(displayText, canvas.width / 2, canvas.height / 2)
          
          const texture = new THREE.CanvasTexture(canvas)
          const spriteMaterial = new THREE.SpriteMaterial({ map: texture, transparent: true })
          const sprite = new THREE.Sprite(spriteMaterial)
          sprite.scale.set(15, 7.5, 1)
          return sprite
        }

        displayNodes.forEach((n) => {
          const typeIndex = typeKeys.indexOf(n.type)
          const groupSize = typeGroups[n.type].length
          const groupIndex = typeGroups[n.type].indexOf(n)

          const baseAngle = typeIndex * typeAngleStep
          const groupOffset = (groupIndex / Math.max(groupSize, 1)) * (typeAngleStep * 0.6) - (typeAngleStep * 0.3)
          const angle = baseAngle + groupOffset

          const radius = 40 + Math.random() * 20
          const x = Math.cos(angle) * radius
          const y = Math.sin(angle) * radius
          const z = (Math.random() - 0.5) * 30

          const isLarge = n.category === 'document'
          const isSelected = n.id === selectedNodeId
          const geometry = isSelected ? selectedGeo : (isLarge ? largeGeo : smallGeo)
          const material = getMaterial(getNodeColor(n.type), isSelected)
          const mesh = new THREE.Mesh(geometry, material)
          mesh.position.set(x, y, z)
          mesh.userData = { ...n, originalColor: getNodeColor(n.type) }

          scene.add(mesh)
          nodeMeshes.push(mesh)
          nodeMap.set(n.id, mesh)

          // 添加文字标签
          const textSprite = createTextSprite(n.name)
          if (textSprite) {
            textSprite.position.set(x, y + (isLarge ? 8 : 6), z)
            textSprite.userData = { nodeId: n.id }
            scene.add(textSprite)
            textSprites.push(textSprite)
          }
        })

        // 创建边 - 批量渲染优化 (LineSegments)
        const lineMaterial = new THREE.LineBasicMaterial({ 
          color: 0xcccccc, 
          transparent: true, 
          opacity: 0.4,
          linewidth: 1
        })
        
        const linePoints: any[] = []
        graphData.edges.forEach(e => {
          if (!nodeIdSet.has(e.source) || !nodeIdSet.has(e.target)) return
          const source = nodeMap.get(e.source)
          const target = nodeMap.get(e.target)
          if (source && target) {
            linePoints.push(source.position)
            linePoints.push(target.position)
          }
        })
        
        if (linePoints.length > 0) {
          const lineGeometry = new THREE.BufferGeometry().setFromPoints(linePoints)
          const lineSegments = new THREE.LineSegments(lineGeometry, lineMaterial)
          scene.add(lineSegments)
        }

        // 鼠标交互
        const raycaster = new THREE.Raycaster()
        const mouse = new THREE.Vector2()
        
        let pointerDownPos = { x: 0, y: 0 }
        
        const onPointerDown = (event: PointerEvent) => {
          pointerDownPos = { x: event.clientX, y: event.clientY }
        }

        const onPointerUp = (event: PointerEvent) => {
          // 判断是否是拖拽
          const dx = event.clientX - pointerDownPos.x
          const dy = event.clientY - pointerDownPos.y
          if (Math.sqrt(dx * dx + dy * dy) > 5) return // 如果移动距离大于 5px，认为是拖拽，不触发点击

          const rect = renderer.domElement.getBoundingClientRect()
          mouse.x = ((event.clientX - rect.left) / width) * 2 - 1
          mouse.y = -((event.clientY - rect.top) / height) * 2 + 1

          raycaster.setFromCamera(mouse, camera)
          const intersects = raycaster.intersectObjects(nodeMeshes)

          if (intersects.length > 0) {
            const node = intersects[0].object.userData
            
            // 停止自动旋转
            controls.autoRotate = false
            
            // 更新选中状态
            setSelectedNodeId(node.id)
            
            // 高亮选中节点
            nodeMeshes.forEach(mesh => {
              const isNodeSelected = mesh.userData.id === node.id
              const color = mesh.userData.originalColor
              mesh.material = getMaterial(color, isNodeSelected)
              mesh.geometry = isNodeSelected ? selectedGeo : (mesh.userData.category === 'document' ? largeGeo : smallGeo)
            })

            handleClick(node)
          }
        }

        renderer.domElement.addEventListener('pointerdown', onPointerDown)
        renderer.domElement.addEventListener('pointerup', onPointerUp)

        // 动画循环
        function animate() {
          if (!isActive) return
          animationId = requestAnimationFrame(animate)

          controls.update() // 更新 OrbitControls

          renderer.render(scene, camera)
        }

        animate()
        setIsLoading(false)
      } catch (error) {
        console.error('Error initializing 3D graph:', error)
        setIsLoading(false)
      }
    }

    init()

    return () => {
      isActive = false
      cancelAnimationFrame(animationId)
      
      if (scene) {
        scene.traverse((object: any) => {
          if (object.geometry) object.geometry.dispose()
          if (object.material) {
            if (Array.isArray(object.material)) {
              object.material.forEach((m: any) => m.dispose())
            } else {
              object.material.dispose()
            }
          }
        })
      }
      
      if (rendererRef.current && containerRef.current && containerRef.current.contains(rendererRef.current.domElement)) {
        containerRef.current.removeChild(rendererRef.current.domElement)
        rendererRef.current.dispose()
      }
    }
  }, [graphData, handleClick, selectedNodeId])

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%', background: '#f8f9fa' }} />
      {isLoading && (
        <div style={{
          position: 'absolute',
          top: 0, left: 0, right: 0, bottom: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'rgba(248,249,250,0.9)',
          zIndex: 10
        }}>
          <div style={{ textAlign: 'center' }}>
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto" />
            <p className="mt-2 text-gray-500 text-sm">加载 3D 图谱...</p>
          </div>
        </div>
      )}
      {graphData.nodes.length === 0 && !isLoading && (
        <div style={{
          position: 'absolute',
          top: 0, left: 0, right: 0, bottom: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'rgba(248,249,250,0.8)',
          zIndex: 10
        }}>
          <p className="text-gray-400">暂无图谱数据</p>
        </div>
      )}
    </div>
  )
}

function getNodeColor(type: string): number {
  // 从共享图例中同步字符串颜色（"#3498db" -> 0x3498db）
  const hex = NODE_COLOR_MAP[type] || '#95a5a6'
  return parseInt(hex.replace('#', ''), 16)
}

export default Graph3D
