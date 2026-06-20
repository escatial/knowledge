import { useState } from 'react'
import AIChat from './AIChat'

function FloatingAI() {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <>
      {/* 浮动按钮 - 现代渐变设计 */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        style={{
          position: 'fixed',
          bottom: 30,
          right: 30,
          width: 60,
          height: 60,
          borderRadius: '50%',
          background: isOpen 
            ? 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
            : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
          color: '#fff',
          border: 'none',
          fontSize: 28,
          cursor: 'pointer',
          boxShadow: isOpen
            ? '0 8px 25px rgba(102, 126, 234, 0.5)'
            : '0 4px 15px rgba(102, 126, 234, 0.4)',
          zIndex: 1000,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transition: 'all 0.3s ease',
          transform: isOpen ? 'scale(0.95) rotate(90deg)' : 'scale(1) rotate(0deg)'
        }}
        onMouseEnter={(e) => {
          if (!isOpen) {
            e.currentTarget.style.transform = 'scale(1.1)'
          }
        }}
        onMouseLeave={(e) => {
          if (!isOpen) {
            e.currentTarget.style.transform = 'scale(1)'
          }
        }}
      >
        {/* 自定义AI图标 */}
        {isOpen ? (
          <svg 
            width="28" 
            height="28" 
            viewBox="0 0 24 24" 
            fill="none" 
            stroke="currentColor" 
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        ) : (
          <svg 
            width="28" 
            height="28" 
            viewBox="0 0 24 24" 
            fill="none" 
            stroke="currentColor" 
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="10" />
            <path d="M12 16v-4" />
            <path d="M12 8h.01" />
            <path d="M9.5 21A2 2 0 0 0 12 19a2 2 0 0 1 2.5 2" />
          </svg>
        )}
      </button>

      {/* 聊天窗口 - 现代UI设计 */}
      {isOpen && (
        <div style={{
          position: 'fixed',
          bottom: 105,
          right: 30,
          width: 400,
          height: 520,
          background: '#fff',
          borderRadius: '20px',
          boxShadow: '0 10px 40px rgba(0,0,0,0.15)',
          zIndex: 999,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          border: '1px solid #e5e7eb'
        }}>
          {/* 头部 - 渐变背景 */}
          <div style={{
            padding: '16px 20px',
            background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
            color: '#fff',
            fontWeight: 600,
            fontSize: 16,
            display: 'flex',
            alignItems: 'center',
            gap: '12px'
          }}>
            {/* 头部图标 */}
            <div style={{
              width: 36,
              height: 36,
              borderRadius: '50%',
              background: 'rgba(255,255,255,0.2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <svg 
                width="20" 
                height="20" 
                viewBox="0 0 24 24" 
                fill="none" 
                stroke="currentColor" 
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="12" cy="12" r="10" />
                <path d="M12 16v-4" />
                <path d="M12 8h.01" />
                <path d="M9.5 21A2 2 0 0 0 12 19a2 2 0 0 1 2.5 2" />
              </svg>
            </div>
            <div>
              <div>AI 知识助手</div>
              <div style={{ fontSize: 12, opacity: 0.9, fontWeight: 400, marginTop: 2 }}>
                在线 · 为您解答
              </div>
            </div>
          </div>
          
          {/* 聊天内容 */}
          <div style={{ flex: 1, overflow: 'hidden' }}>
            <AIChat embedded={true} />
          </div>
        </div>
      )}
    </>
  )
}

export default FloatingAI
