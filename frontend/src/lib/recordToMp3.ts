import { Mp3Encoder } from 'lamejs'

const MP3_SAMPLE_RATE = 44100
const MP3_KBPS = 128
const CHUNK_SAMPLES = 1152

function mixToMono(buffer: AudioBuffer): Float32Array {
  const n = buffer.numberOfChannels
  const len = buffer.length
  if (n === 1) {
    return buffer.getChannelData(0)
  }
  const out = new Float32Array(len)
  for (let c = 0; c < n; c++) {
    const ch = buffer.getChannelData(c)
    for (let i = 0; i < len; i++) {
      out[i] += ch[i] / n
    }
  }
  return out
}

function resampleLinear(input: Float32Array, inputRate: number, outputRate: number): Float32Array {
  if (inputRate === outputRate) {
    return input
  }
  const ratio = inputRate / outputRate
  const outLength = Math.max(1, Math.round(input.length / ratio))
  const out = new Float32Array(outLength)
  for (let i = 0; i < outLength; i++) {
    const srcIndex = i * ratio
    const j = Math.floor(srcIndex)
    const f = srcIndex - j
    const a = input[j] ?? 0
    const b = input[j + 1] ?? a
    out[i] = a + (b - a) * f
  }
  return out
}

function floatTo16BitPCM(float32: Float32Array): Int16Array {
  const out = new Int16Array(float32.length)
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]))
    out[i] = s < 0 ? (s * 0x8000) | 0 : (s * 0x7fff) | 0
  }
  return out
}

function encodePcmToMp3Blob(pcm: Int16Array): Blob {
  const enc = new Mp3Encoder(1, MP3_SAMPLE_RATE, MP3_KBPS)
  const parts: Uint8Array[] = []
  for (let i = 0; i < pcm.length; i += CHUNK_SAMPLES) {
    const chunk = pcm.subarray(i, i + CHUNK_SAMPLES)
    const buf = enc.encodeBuffer(chunk)
    if (buf.length > 0) {
      parts.push(new Uint8Array(buf))
    }
  }
  const tail = enc.flush()
  if (tail.length > 0) {
    parts.push(new Uint8Array(tail))
  }
  const total = parts.reduce((a, p) => a + p.length, 0)
  const merged = new Uint8Array(total)
  let off = 0
  for (const p of parts) {
    merged.set(p, off)
    off += p.length
  }
  return new Blob([merged], { type: 'audio/mpeg' })
}

/**
 * Декодирует запись браузера (WebM/OGG/…) в моно PCM 44.1 kHz и кодирует в MP3.
 */
export async function recordedBlobToMp3File(recorded: Blob, filename = 'voice.mp3'): Promise<File> {
  const raw = await recorded.arrayBuffer()
  const ctx = new AudioContext()
  let audio: AudioBuffer
  try {
    audio = await ctx.decodeAudioData(raw.slice(0))
  } finally {
    await ctx.close().catch(() => {})
  }
  const mono = mixToMono(audio)
  const resampled = resampleLinear(mono, audio.sampleRate, MP3_SAMPLE_RATE)
  const pcm = floatTo16BitPCM(resampled)
  const blob = encodePcmToMp3Blob(pcm)
  return new File([blob], filename, { type: 'audio/mpeg' })
}

export function preferredRecorderMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined' || !MediaRecorder.isTypeSupported) {
    return undefined
  }
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
  for (const t of candidates) {
    if (MediaRecorder.isTypeSupported(t)) {
      return t
    }
  }
  return undefined
}
