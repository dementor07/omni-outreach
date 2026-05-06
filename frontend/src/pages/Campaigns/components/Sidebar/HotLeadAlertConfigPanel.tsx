import React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Node } from '@xyflow/react'
import { api } from '../../../../api/client'
import { NotificationChannel } from '../../types'
import { labelCls, inputClassName } from './Common'

export function HotLeadAlertConfigPanel({ node, onUpdate }: { node: Node; onUpdate: (data: any) => void }) {
  const channelsQuery = useQuery<NotificationChannel[]>({
    queryKey: ['notification-channels'],
    queryFn: async () => (await api.get<NotificationChannel[]>('/settings/notification-channels')).data,
  })
  const data = (node.data as any) || {}
  const selectedIds: string[] = data.channel_ids || []
  const channels = (channelsQuery.data || []).filter(c => c.is_active)

  const toggle = (id: string) => {
    const next = selectedIds.includes(id) ? selectedIds.filter(x => x !== id) : [...selectedIds, id]
    onUpdate({ channel_ids: next })
  }

  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Title</label>
        <input
          type="text"
          value={data.title || ''}
          onChange={(e) => onUpdate({ title: e.target.value })}
          className={inputClassName}
          placeholder="🔥 Hot lead: {{first_name}} {{last_name}}"
        />
      </div>
      <div>
        <label className={labelCls}>Message</label>
        <textarea
          value={data.body || ''}
          onChange={(e) => onUpdate({ body: e.target.value })}
          className={inputClassName + ' min-h-[90px]'}
          rows={4}
          placeholder="{{first_name}} at {{company}} replied positively. Reach out now."
        />
      </div>
      <div>
        <label className={labelCls}>Channels</label>
        {channels.length === 0 ? (
          <p className="text-[11px] text-slate-500">No active channels. Add one in <Link to="/settings?tab=integrations" className="text-sky-600 hover:underline">Settings → Integrations</Link>.</p>
        ) : (
          <div className="space-y-1">
            {channels.map(ch => {
              const checked = selectedIds.includes(ch.id) || selectedIds.length === 0
              return (
                <label key={ch.id} className="flex items-center gap-3 rounded-xl px-3 py-2 hover:bg-slate-50 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(ch.id)}
                    onChange={() => toggle(ch.id)}
                    className="h-4 w-4 rounded border-slate-300 text-sky-500 focus:ring-sky-500"
                  />
                  <span className="text-sm font-medium text-slate-700">{ch.name}</span>
                  <span className="text-[10px] uppercase text-slate-400">{ch.channel_type}</span>
                  {!checked && selectedIds.length === 0 && (
                    <span className="ml-auto text-[10px] text-slate-400">(all by default)</span>
                  )}
                </label>
              )
            })}
            <p className="text-[10px] text-slate-400 pt-1">Leave all unchecked to broadcast to every active channel.</p>
          </div>
        )}
      </div>
    </div>
  )
}
