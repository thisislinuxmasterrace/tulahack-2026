export type RedactionCategory =
  | 'passport'
  | 'inn'
  | 'snils'
  | 'phone'
  | 'email'
  | 'address'

export interface TranscriptSegment {
  text: string
  sensitive?: boolean
  category?: RedactionCategory
}

export interface TimelineRedaction {
  start: number
  end: number
  category: RedactionCategory
}

export interface RedactionStat {
  category: RedactionCategory
  label: string
  count: number
  examples: string[]
}
