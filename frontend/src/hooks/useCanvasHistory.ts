import { useCallback, useRef, useState } from 'react'
import type { Node, Edge } from '@xyflow/react'

interface HistoryEntry {
  nodes: Node[]
  edges: Edge[]
}

const MAX_HISTORY = 50

export function useCanvasHistory() {
  const historyRef = useRef<HistoryEntry[]>([])
  const indexRef = useRef(-1)
  const [canUndo, setCanUndo] = useState(false)
  const [canRedo, setCanRedo] = useState(false)

  const pushState = useCallback((nodes: Node[], edges: Edge[]) => {
    // Truncate any future states
    historyRef.current = historyRef.current.slice(0, indexRef.current + 1)
    historyRef.current.push({
      nodes: JSON.parse(JSON.stringify(nodes)),
      edges: JSON.parse(JSON.stringify(edges)),
    })
    // Limit history size
    if (historyRef.current.length > MAX_HISTORY) {
      historyRef.current.shift()
    } else {
      indexRef.current += 1
    }
    setCanUndo(indexRef.current > 0)
    setCanRedo(false)
  }, [])

  const undo = useCallback((): HistoryEntry | null => {
    if (indexRef.current <= 0) return null
    indexRef.current -= 1
    const entry = historyRef.current[indexRef.current]
    setCanUndo(indexRef.current > 0)
    setCanRedo(true)
    return {
      nodes: JSON.parse(JSON.stringify(entry.nodes)),
      edges: JSON.parse(JSON.stringify(entry.edges)),
    }
  }, [])

  const redo = useCallback((): HistoryEntry | null => {
    if (indexRef.current >= historyRef.current.length - 1) return null
    indexRef.current += 1
    const entry = historyRef.current[indexRef.current]
    setCanUndo(true)
    setCanRedo(indexRef.current < historyRef.current.length - 1)
    return {
      nodes: JSON.parse(JSON.stringify(entry.nodes)),
      edges: JSON.parse(JSON.stringify(entry.edges)),
    }
  }, [])

  const reset = useCallback(() => {
    historyRef.current = []
    indexRef.current = -1
    setCanUndo(false)
    setCanRedo(false)
  }, [])

  return { pushState, undo, redo, reset, canUndo, canRedo }
}
