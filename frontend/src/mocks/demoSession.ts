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

export const demoFileName = 'call_2026-04-17_143022.wav'
export const demoDurationSec = 124

export const demoTranscriptSegments: TranscriptSegment[] = [
  { text: 'Добрый день, ' },
  { text: 'слушаю отдел кадров.', sensitive: true, category: 'address' },
  { text: ' Меня зовут Мария. ' },
  { text: 'Мой ИНН 7707083893', sensitive: true, category: 'inn' },
  { text: ', СНИЛС 128-656-391 07', sensitive: true, category: 'snils' },
  { text: '. Перезвоните на ' },
  { text: '+7 916 123-45-67', sensitive: true, category: 'phone' },
  { text: ' или на почту ' },
  { text: 'maria.ivanova@mail.ru', sensitive: true, category: 'email' },
  { text: '. Паспорт ' },
  { text: '45 12 654321', sensitive: true, category: 'passport' },
  { text: ', выдан УФМС. Спасибо.' },
]

export const demoSanitizedPlain =
  'Добрый день, [адрес скрыт]. Меня зовут Мария. [ИНН] [СНИЛС]. Перезвоните на [телефон] или на [email]. Паспорт [скрыто], выдан УФМС. Спасибо.'

export const demoTimelineRedactions: TimelineRedaction[] = [
  { start: 0.08, end: 0.18, category: 'address' },
  { start: 0.22, end: 0.42, category: 'inn' },
  { start: 0.42, end: 0.52, category: 'snils' },
  { start: 0.55, end: 0.65, category: 'phone' },
  { start: 0.66, end: 0.78, category: 'email' },
  { start: 0.8, end: 0.92, category: 'passport' },
]

export const demoRedactionStats: RedactionStat[] = [
  {
    category: 'passport',
    label: 'Паспортные данные',
    count: 1,
    examples: ['45 ** *****'],
  },
  {
    category: 'inn',
    label: 'ИНН',
    count: 1,
    examples: ['7707******'],
  },
  {
    category: 'snils',
    label: 'СНИЛС',
    count: 1,
    examples: ['128-***-*** 07'],
  },
  {
    category: 'phone',
    label: 'Телефон',
    count: 1,
    examples: ['+7 *** ***-**-67'],
  },
  {
    category: 'email',
    label: 'E-mail',
    count: 1,
    examples: ['ma***@mail.ru'],
  },
  {
    category: 'address',
    label: 'Адрес / принадлежность',
    count: 1,
    examples: ['отдел кадров'],
  },
]
