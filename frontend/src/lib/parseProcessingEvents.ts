import type { ProcessingLogEntry, ProcessingLogLevel } from '../types/processingLog'

const LEVELS = new Set<ProcessingLogLevel>(['info', 'warning', 'error'])

function isLevel(s: string): s is ProcessingLogLevel {
  return LEVELS.has(s as ProcessingLogLevel)
}

export function parseProcessingLogEntries(raw: unknown): ProcessingLogEntry[] {
  if (!Array.isArray(raw)) return []
  const out: ProcessingLogEntry[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const o = item as Record<string, unknown>
    const ts = o.ts
    const level = o.level
    const message = o.message
    if (typeof ts !== 'string' || typeof message !== 'string' || typeof level !== 'string' || !isLevel(level)) {
      continue
    }
    out.push({ ts, level, message })
  }
  return out
}
