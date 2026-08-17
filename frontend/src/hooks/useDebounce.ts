import { useEffect, useState } from 'react'

/** Returns `value` after it has stopped changing for `delay` ms. Used to debounce
 *  search inputs so a keystroke doesn't fire a request per character. */
export function useDebounce<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState<T>(value)
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(handle)
  }, [value, delay])
  return debounced
}
