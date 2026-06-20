/**
 * 轻量级状态管理 + localStorage 持久化
 * 不依赖 zustand/redux，单文件实现，支持 React 订阅。
 */
import { useEffect, useState } from 'react'

type Listener<T> = (state: T) => void

interface StoreOptions {
  /** localStorage key，启用持久化 */
  persistKey?: string
}

export function create<T>(initial: T, options: StoreOptions = {}) {
  let state: T = initial
  // 启动时从 localStorage 恢复
  if (options.persistKey) {
    try {
      const raw = localStorage.getItem(options.persistKey)
      if (raw) {
        state = { ...initial, ...JSON.parse(raw) } as T
      }
    } catch (e) {
      console.warn('[tinyStore] 恢复失败:', e)
    }
  }

  const listeners = new Set<Listener<T>>()

  const persist = () => {
    if (options.persistKey) {
      try {
        localStorage.setItem(options.persistKey, JSON.stringify(state))
      } catch (e) {
        console.warn('[tinyStore] 持久化失败:', e)
      }
    }
  }

  const setState = (updater: T | ((prev: T) => T)) => {
    const next =
      typeof updater === 'function' ? (updater as (p: T) => T)(state) : updater
    state = next
    persist()
    listeners.forEach((l) => l(state))
  }

  const getState = () => state

  const subscribe = (l: Listener<T>) => {
    listeners.add(l)
    return () => listeners.delete(l)
  }

  // React hook
  const useStore = <S>(selector: (s: T) => S = (s) => s as unknown as S): S => {
    const [val, setVal] = useState<S>(() => selector(state))
    useEffect(() => {
      const unsub = subscribe((s) => {
        const next = selector(s)
        setVal((prev) => {
          if (Object.is(prev, next)) return prev
          return next
        })
      })
      // 立即同步一次（防止外部修改后组件没刷新）
      setVal(selector(state))
      return () => { unsub() }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])
    return val
  }

  return { getState, setState, subscribe, useStore }
}
