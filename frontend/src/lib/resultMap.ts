import type {
  RedactionCategory,
  RedactionStat,
  TimelineRedaction,
  TranscriptSegment,
} from '../mocks/demoSession'

const categoryLabels: Record<string, string> = {
  passport: 'Паспортные данные',
  inn: 'ИНН',
  snils: 'СНИЛС',
  phone: 'Телефон',
  email: 'E-mail',
  address: 'Адрес / принадлежность',
}

export function statusLabelRu(status: string): string {
  const m: Record<string, string> = {
    queued: 'В очереди',
    running: 'Запуск',
    stt: 'Распознавание речи',
    llm: 'Поиск персональных данных',
    render_audio: 'Обработка аудио',
    done: 'Готово',
    failed: 'Ошибка',
    cancelled: 'Отменено',
  }
  return m[status] ?? status
}

export function statusStageHintRu(status: string): string {
  const m: Record<string, string> = {
    queued: 'Запись ждёт своей очереди — обычно это занимает немного времени.',
    running: 'Файл принят, идёт подготовка к распознаванию.',
    stt: 'Распознаётся речь и формируется текст записи.',
    llm: 'Ищутся и скрываются персональные данные в тексте.',
    render_audio: 'Обрабатывается аудио: фрагменты с персональными данными приглушаются или заменяются.',
    done: 'Обработка завершена.',
    failed: 'При обработке произошла ошибка.',
    cancelled: 'Обработка отменена.',
  }
  return m[status] ?? 'Идёт обработка…'
}

const entityCategories: RedactionCategory[] = [
  'passport',
  'inn',
  'snils',
  'phone',
  'email',
  'address',
]

function isRedactionCategory(s: string): s is RedactionCategory {
  return entityCategories.includes(s as RedactionCategory)
}

export function plainTextFromJob(whisper: unknown, fallbackPlain: string): string {
  const fromPlain = fallbackPlain.trim()
  if (fromPlain) return fromPlain
  if (whisper && typeof whisper === 'object') {
    const w = whisper as { text?: string; segments?: Array<{ text?: string }> }
    const t = (w.text ?? '').trim()
    if (t) return t
    const segs = w.segments
    if (Array.isArray(segs) && segs.length > 0) {
      const joined = segs
        .map((s) => (s.text ?? '').trim())
        .filter(Boolean)
        .join(' ')
      if (joined) return joined
    }
  }
  return ''
}

type CharSpan = { start: number; end: number; category: RedactionCategory }

function parseLlmEntitySpans(entities: unknown, textLen: number): CharSpan[] {
  if (!Array.isArray(entities) || textLen <= 0) return []
  const raw: CharSpan[] = []
  for (const item of entities) {
    if (!item || typeof item !== 'object') continue
    const o = item as Record<string, unknown>
    const sc = o.start_char
    const ec = o.end_char
    if (typeof sc !== 'number' || typeof ec !== 'number') continue
    if (ec <= sc) continue
    const start = Math.max(0, Math.min(sc, textLen))
    const end = Math.max(start, Math.min(ec, textLen))
    if (end <= start) continue
    const et = String(o.entity_type ?? '').toLowerCase()
    const category: RedactionCategory = isRedactionCategory(et) ? et : 'phone'
    raw.push({ start, end, category })
  }
  raw.sort((a, b) => a.start - b.start || b.end - a.end)
  return mergeCharSpans(raw)
}

function mergeCharSpans(spans: CharSpan[]): CharSpan[] {
  if (spans.length === 0) return []
  const out: CharSpan[] = []
  let cur = { ...spans[0] }
  for (let i = 1; i < spans.length; i++) {
    const s = spans[i]
    if (s.start < cur.end) {
      cur.end = Math.max(cur.end, s.end)
    } else {
      out.push(cur)
      cur = { ...s }
    }
  }
  out.push(cur)
  return out
}

export function segmentsFromPlainAndEntities(plain: string, entities: unknown): TranscriptSegment[] {
  const t = plain.trim()
  if (!t) return [{ text: '—' }]
  const spans = parseLlmEntitySpans(entities, t.length)
  if (spans.length === 0) return [{ text: t }]
  const segs: TranscriptSegment[] = []
  let cursor = 0
  for (const s of spans) {
    if (s.start > cursor) {
      segs.push({ text: t.slice(cursor, s.start) })
    }
    if (s.end > s.start) {
      segs.push({
        text: t.slice(s.start, s.end),
        sensitive: true,
        category: s.category,
      })
    }
    cursor = Math.max(cursor, s.end)
  }
  if (cursor < t.length) {
    segs.push({ text: t.slice(cursor) })
  }
  return segs.length > 0 ? segs : [{ text: t }]
}

export function segmentsFromJob(
  whisper: unknown,
  fallbackPlain: string,
  llmEntities?: unknown,
): TranscriptSegment[] {
  const plain = plainTextFromJob(whisper, fallbackPlain)
  if (!plain) {
    return [{ text: '—' }]
  }
  if (llmEntities !== undefined && llmEntities !== null) {
    const marked = segmentsFromPlainAndEntities(plain, llmEntities)
    if (marked.some((s) => s.sensitive)) {
      return marked
    }
  }
  return [{ text: plain }]
}

export function statsFromReport(report: unknown): RedactionStat[] {
  if (!report || typeof report !== 'object') return []
  const r = report as { counts?: Record<string, number>; examples?: Record<string, string[]> }
  const counts = r.counts
  if (!counts || typeof counts !== 'object') return []
  const examples = r.examples ?? {}
  return Object.entries(counts).map(([category, count]) => ({
    category: category as RedactionCategory,
    label: categoryLabels[category] ?? category,
    count,
    examples: examples[category] ?? [],
  }))
}

export function timelineFromReport(report: unknown, durationSec: number): TimelineRedaction[] {
  if (!report || typeof report !== 'object' || durationSec <= 0) return []
  const spans = (report as { spans?: Array<{ type?: string; start_ms?: number; end_ms?: number }> }).spans
  if (!Array.isArray(spans)) return []
  return spans
    .map((s) => {
      const start = ((s.start_ms ?? 0) / 1000 / durationSec) as number
      const end = ((s.end_ms ?? 0) / 1000 / durationSec) as number
      const category = (s.type ?? 'phone') as RedactionCategory
      return { start: Math.min(1, Math.max(0, start)), end: Math.min(1, Math.max(0, end)), category }
    })
    .filter((x) => x.end > x.start)
}

export function durationFromWhisper(whisper: unknown): number {
  if (whisper && typeof whisper === 'object' && 'duration_sec' in whisper) {
    const d = (whisper as { duration_sec?: number }).duration_sec
    if (typeof d === 'number' && d > 0) return d
  }
  return 0
}
