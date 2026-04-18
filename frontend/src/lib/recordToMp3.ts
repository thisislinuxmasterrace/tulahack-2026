import { getMp3EncoderClass } from './lameLoader'

const MP3_SAMPLE_RATE = 44100
const MP3_KBPS = 128
const CHUNK_SAMPLES = 1152

const LOG = '[record-mp3]'

function dbg(...args: unknown[]) {
  console.log(LOG, ...args)
}

function dbgWarn(...args: unknown[]) {
  console.warn(LOG, ...args)
}

function dbgErr(...args: unknown[]) {
  console.error(LOG, ...args)
}

function audioContextCtor(): typeof AudioContext {
  const w = window as unknown as { webkitAudioContext?: typeof AudioContext }
  return window.AudioContext ?? w.webkitAudioContext ?? AudioContext
}

export function isLiveCaptureSupported(): boolean {
  if (typeof window === 'undefined') {
    return false
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return false
  }
  const w = window as unknown as { webkitAudioContext?: typeof AudioContext }
  const Ctor = window.AudioContext ?? w.webkitAudioContext
  if (typeof Ctor !== 'function') {
    return false
  }
  const hasScriptProcessor = typeof Ctor.prototype.createScriptProcessor === 'function'
  if (!hasScriptProcessor) {
    dbgWarn('isLiveCaptureSupported: false — createScriptProcessor отсутствует (часть браузеров убрала API)')
  }
  return hasScriptProcessor
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

/** Как у шлюза: макс. 50 MiB (см. backend maxUploadBytes). */
export const CLIENT_MAX_AUDIO_BYTES = 50 << 20

function mixAudioBufferToMono(buffer: AudioBuffer): Float32Array {
  const n = buffer.numberOfChannels
  const len = buffer.length
  if (n === 1) {
    return Float32Array.from(buffer.getChannelData(0))
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

/**
 * Любой формат, который умеет декодировать браузер → MP3 (моно 44.1 kHz).
 * Уже `.mp3` возвращает тот же файл без перекодирования.
 */
export async function convertAudioFileToMp3IfNeeded(file: File): Promise<File> {
  if (file.size > CLIENT_MAX_AUDIO_BYTES) {
    throw new Error('file_too_large')
  }
  const lower = file.name.trim().toLowerCase()
  if (lower.endsWith('.mp3')) {
    dbg('convertAudioFileToMp3IfNeeded: pass-through', file.name)
    return file
  }
  dbg('convertAudioFileToMp3IfNeeded: decode+encode', file.name, file.type, file.size)
  const raw = await file.arrayBuffer()
  const AC = audioContextCtor()
  const ctx = new AC()
  let audio: AudioBuffer
  try {
    audio = await ctx.decodeAudioData(raw.slice(0))
  } catch (err) {
    dbgErr('decodeAudioData failed', err)
    throw new Error('decode_failed')
  } finally {
    await ctx.close().catch(() => {})
  }
  const mono = mixAudioBufferToMono(audio)
  const base = file.name.replace(/[/\\]/g, '').replace(/\.[^.]+$/, '') || 'audio'
  const outName = `${base}.mp3`
  return floatMonoToMp3File(mono, audio.sampleRate, outName)
}

async function encodePcmToMp3Blob(pcm: Int16Array): Promise<Blob> {
  dbg('encodePcmToMp3Blob: pcm samples', pcm.length)
  const Mp3Encoder = await getMp3EncoderClass()
  const enc = new Mp3Encoder(1, MP3_SAMPLE_RATE, MP3_KBPS)
  const parts: Uint8Array[] = []
  try {
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
  } catch (err) {
    dbgErr('encodePcmToMp3Blob: lamejs threw', err)
    throw err
  }
  const total = parts.reduce((a, p) => a + p.length, 0)
  const merged = new Uint8Array(total)
  let off = 0
  for (const p of parts) {
    merged.set(p, off)
    off += p.length
  }
  dbg('encodePcmToMp3Blob: output bytes', merged.length)
  return new Blob([merged], { type: 'audio/mpeg' })
}

/**
 * Моно PCM (float −1…1) с исходной частотой дискретизации → MP3 44.1 kHz.
 */
export async function floatMonoToMp3File(
  samples: Float32Array,
  sourceSampleRate: number,
  filename: string,
): Promise<File> {
  dbg('floatMonoToMp3File: input length', samples.length, 'sourceSampleRate', sourceSampleRate, filename)
  if (samples.length < 64) {
    dbgErr('floatMonoToMp3File: too_short', { length: samples.length })
    throw new Error('too_short')
  }
  try {
    const resampled = resampleLinear(samples, sourceSampleRate, MP3_SAMPLE_RATE)
    dbg('floatMonoToMp3File: after resample', resampled.length)
    const pcm = floatTo16BitPCM(resampled)
    const blob = await encodePcmToMp3Blob(pcm)
    const file = new File([blob], filename, { type: 'audio/mpeg' })
    dbg('floatMonoToMp3File: done file.size', file.size)
    return file
  } catch (err) {
    dbgErr('floatMonoToMp3File: error', err)
    if (err instanceof Error) {
      dbgErr('floatMonoToMp3File: stack', err.stack)
    }
    throw err
  }
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
  let pcmFramesSeen = 0

  const cleanupGraph = async () => {
    dbg('cleanupGraph')
    try {
      processor?.disconnect()
      source?.disconnect()
      mute?.disconnect()
    } catch (err) {
      dbgWarn('cleanupGraph: disconnect', err)
    }
    processor = null
    source = null
    mute = null
    if (ctx) {
      try {
        const st = ctx.state
        await ctx.close()
        dbg('cleanupGraph: AudioContext closed, was', st)
      } catch (err) {
        dbgWarn('cleanupGraph: ctx.close', err)
      }
    }
    ctx = null
    if (stream) {
      stream.getTracks().forEach((t) => {
        dbg('cleanupGraph: stop track', t.kind, t.label, 'enabled=', t.enabled)
        t.stop()
      })
      stream = null
    }
  }

  return {
    async start(): Promise<void> {
      dbg('start()')
      pcmFramesSeen = 0
      try {
        live = false
        await cleanupGraph()
        chunkList.length = 0
        dbg('getUserMedia…')
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
          },
        })
        const tracks = stream.getAudioTracks()
        dbg('getUserMedia OK, audio tracks:', tracks.length, tracks.map((t) => ({ label: t.label, enabled: t.enabled, muted: t.muted })))

        const AC = audioContextCtor()
        ctx = new AC()
        dbg('AudioContext created, state=', ctx.state, 'sampleRate=', ctx.sampleRate)
        await ctx.resume()
        dbg('AudioContext after resume, state=', ctx.state)

        source = ctx.createMediaStreamSource(stream)
        dbg('MediaStreamSource channelCount=', source.channelCount)
        const bufferSize = 4096
        dbg('createScriptProcessor(', bufferSize, ', 2, 2)')
        processor = ctx.createScriptProcessor(bufferSize, 2, 2)

        processor.onaudioprocess = (e: AudioProcessingEvent) => {
          if (!live) {
            return
          }
          const b = e.inputBuffer
          const len = b.length
          const n = b.numberOfChannels
          pcmFramesSeen += 1
          if (pcmFramesSeen === 1) {
            dbg('first onaudioprocess: len', len, 'channels', n)
          } else if (pcmFramesSeen % 50 === 0) {
            dbg('onaudioprocess frames', pcmFramesSeen, 'chunks stored', chunkList.length)
          }
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
        dbg('start() OK, live=true, waiting for audio buffers…')
      } catch (err) {
        dbgErr('start() failed', err)
        if (err instanceof Error) {
          dbgErr('start() message', err.message, err.stack)
        }
        await cleanupGraph()
        chunkList.length = 0
        throw err
      }
    },

    async stop(filename: string): Promise<File> {
      dbg('stop() requested', { filename, pcmFramesSeen, chunkListLength: chunkList.length })
      const rate = ctx?.sampleRate ?? MP3_SAMPLE_RATE
      dbg('stop(): using sampleRate', rate)
      live = false
      await cleanupGraph()

      const total = chunkList.reduce((a, c) => a + c.length, 0)
      dbg('stop(): merged PCM length', total, 'chunks', chunkList.length)
      if (total < 64) {
        dbgErr('stop(): too_short', { total, pcmFramesSeen })
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
      try {
        return await floatMonoToMp3File(merged, rate, filename)
      } catch (err) {
        dbgErr('stop(): floatMonoToMp3File failed', err)
        throw err
      }
    },

    cancel(): void {
      dbg('cancel()')
      live = false
      chunkList.length = 0
      void cleanupGraph()
    },
  }
}
