import { createContext, useContext } from 'react'

interface ExpandCtx {
  expandedIds: Set<string>
  toggle: (id: string) => void
}

export const ExpandContext = createContext<ExpandCtx>({
  expandedIds: new Set(),
  toggle: () => {},
})

export function useExpand() {
  return useContext(ExpandContext)
}
