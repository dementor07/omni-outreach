import { clsx } from 'clsx'
import { Mail, Linkedin, MessageSquare, Phone, Smartphone } from 'lucide-react'
import type { LucideProps } from 'lucide-react'
import type { ForwardRefExoticComponent, RefAttributes } from 'react'

type LucideIcon = ForwardRefExoticComponent<Omit<LucideProps, 'ref'> & RefAttributes<SVGSVGElement>>

const CHANNEL_META: Record<string, { icon: LucideIcon; label: string; tone: string }> = {
  email:           { icon: Mail,          label: 'Email',     tone: 'info' },
  linkedin:        { icon: Linkedin,      label: 'LinkedIn',  tone: 'brand' },
  linkedin_dm:     { icon: Linkedin,      label: 'LinkedIn',  tone: 'brand' },
  linkedin_invite: { icon: Linkedin,      label: 'LinkedIn',  tone: 'brand' },
  linkedin_inmail: { icon: Linkedin,      label: 'InMail',    tone: 'brand' },
  whatsapp:        { icon: MessageSquare,  label: 'WhatsApp',  tone: 'success' },
  sms:             { icon: Smartphone,     label: 'SMS',       tone: 'violet' },
  voice:           { icon: Phone,          label: 'Voice',     tone: 'violet' },
}

const channelTone: Record<string, { bg: string; text: string; dark: string }> = {
  info:    { bg: 'bg-sky-50',     text: 'text-sky-600',     dark: 'dark:bg-sky-900/30 dark:text-sky-400' },
  brand:   { bg: 'bg-brand-50',   text: 'text-brand-600',   dark: 'dark:bg-brand-900/30 dark:text-brand-400' },
  success: { bg: 'bg-emerald-50', text: 'text-emerald-600', dark: 'dark:bg-emerald-900/30 dark:text-emerald-400' },
  violet:  { bg: 'bg-violet-50',  text: 'text-violet-600',  dark: 'dark:bg-violet-900/30 dark:text-violet-400' },
}

interface ChannelIconProps {
  channel: string
  size?: 'sm' | 'md' | 'lg'
}

export default function ChannelIcon({ channel, size = 'md' }: ChannelIconProps) {
  const meta = CHANNEL_META[channel] || CHANNEL_META.email
  const tone = channelTone[meta.tone] || channelTone.info
  const sz = size === 'sm' ? 'h-7 w-7' : size === 'lg' ? 'h-10 w-10' : 'h-8 w-8'
  const ic = size === 'sm' ? 12 : size === 'lg' ? 16 : 14
  const IconComp = meta.icon
  return (
    <span className={clsx('inline-flex flex-shrink-0 items-center justify-center rounded-lg', sz, tone.bg, tone.text, tone.dark)}>
      <IconComp size={ic} />
    </span>
  )
}

export { CHANNEL_META }
