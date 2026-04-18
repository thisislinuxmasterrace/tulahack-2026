import { Mp3Encoder } from 'lamejs'

const MP3_SAMPLE_RATE = 44100
const MP3_KBPS = 128
const CHUNK_SAMPLES = 1152

function audioContextCtor(): typeof AudioContext {
  const w = window as unknown as { webkitAudioContext?: typeof AudioContext }
  return window.AudioContext ?? w.webkitAudioContext ?? AudioContext
}

export function isLiveCaptureSupported(): boolean {
  if (typeof window === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
    return false
  }
  const w = window as unknown as { webkitAudioContext?: typeof AudioContext }
  const Ctor = window.AudioContext ?? w.webkitAudioContext
  return typeof Ctor === 'function' && typeof Ctor.prototype.createScriptProcessor === 'function'
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
 * Моно PCM (float −1…1) с исходной частотой дискретизации → MP3 44.1 kHz.
 */
export function floatMonoToMp3File(samples: Float32Array, sourceSampleRate: number, filename: string): File {
  if (samples.length < 64) {
    throw new Error('too_short')
  }
  const resampled = resampleLinear(samples, sourceSampleRate, MP3_SAMPLE_RATE)
  const pcm = floatTo16BitPCM(resampled)
  const blob = encodePcmToMp3Blob(pcm)
  return new File([blob], filename, { type: 'audio/mpeg' })
}

export type LiveMp3Capture = {
  start: () => Promise<void>
  stop: (filename: string) => Promise<File>
  cancel: () => void
}

/** Запись с микрофона в PCM через Web Audio (без MediaRecorder / decodeAudioData — совместимо с Safari). */
export function createLiveMp3Capture(): LiveMp3Capture {
  let ctx: AudioContext | null = null
  let stream: MediaStream | null = null
  let source: MediaStreamAudioSourceNode | null = null
  let processor: ScriptProcessorNode | null = null
  let mute: GainNode | null = null
  let live = false
  const chunkList: Float32Array[] = []

  const cleanupGraph = async () => {
    try {
      processor?.disconnect()
      source?.disconnect()
      mute?.disconnect()
    } catch {
      /* ignore */
    }
    processor = null
    source = null
    mute = null
    if (ctx) {
      try {
        await ctx.close()
      } catch {
        /* ignore */
      }
    }
    ctx = null
    if (stream) {
      stream.getTracks().forEach((t) => t.stop())
      stream = null
    }
  }

  return {
    async start(): Promise<void> {
      live = false
      await cleanupGraph()
      chunkList.length = 0
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
        },
      })
      const AC = audioContextCtor()
      ctx = new AC()
      await ctx.resume()

      source = ctx.createMediaStreamSource(stream)
      const bufferSize = 4096
      processor = ctx.createScriptProcessor(bufferSize, 2, 2)

      processor.onaudioprocess = (e: AudioProcessingEvent) => {
        if (!live) {
          return
        }
        const b = e.inputBuffer
        const len = b.length
        const n = b.numberOfChannels
        const mono = new Float32Array(len)
        if (n === 1) {
          mono.set(b.getChannelData(0))
        } else {
          for (let c = 0; c < n; c++) {
            const ch = b.getChannelData(c)
            for (let i = 0; i < len; i++) {
              mono[i] += ch[i] / n
            }
          }
        }
        chunkList.push(mono)
      }

      mute = ctx.createGain()
      mute.gain.value = 0
      source.connect(processor)
      processor.connect(mute)
      mute.connect(ctx.destination)

      live = true
    },

    async stop(filename: string): Promise<File> {
      const rate = ctx?.sampleRate ?? MP3_SAMPLE_RATE
      live = false
      await cleanupGraph()

      const total = chunkList.reduce((a, c) => a + c.length, 0)
      if (total < 64) {
        chunkList.length = 0
        throw new Error('too_short')
      }
      const merged = new Float32Array(total)
      let off = 0
      for (const c of chunkList) {
        merged.set(c, off)
        off += c.length
      }
      chunkList.length = 0
      return floatMonoToMp3File(merged, rate, filename)
    },

    cancel(): void {
      live = false
      chunkList.length = 0
      void cleanupGraph()
    },
  }
}
