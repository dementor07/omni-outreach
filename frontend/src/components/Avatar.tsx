const PALETTE = ['#0ea5e9', '#10b981', '#f59e0b', '#f43f5e', '#8b5cf6', '#06b6d4']

function initials(name = '') {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  return (parts[0][0] + (parts[1]?.[0] || '')).toUpperCase()
}

interface AvatarProps {
  name: string
  size?: number
  color?: string
}

export default function Avatar({ name, size = 32, color }: AvatarProps) {
  const hash = [...(name || '?')].reduce((a, c) => a + c.charCodeAt(0), 0)
  const bg = color || PALETTE[hash % PALETTE.length]
  return (
    <span
      className="inline-flex items-center justify-center rounded-full font-semibold text-white"
      style={{ width: size, height: size, background: bg, fontSize: size * 0.42 }}
    >
      {initials(name)}
    </span>
  )
}
