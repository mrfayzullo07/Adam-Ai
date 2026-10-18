/**
 * AudioWorklet: mikrofon float32 (AudioContext sampleRate, odatda 44.1/48 kHz) ->
 * 16 kHz mono Int16 PCM, ~100 ms chunk'lar. Audio thread'da ishlaydi (ScriptProcessor yo'q).
 *
 * Downsampling: har chiqish namunasi uchun kirish oynasidagi o'rtacha qiymat
 * (box-filter) — nutq uchun yetarli anti-aliasing beradi.
 * Asosiy thread'ga: { type: "chunk", buffer: ArrayBuffer(Int16), level: RMS 0..1 }
 */
class PcmRecorderProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const opts = (options && options.processorOptions) || {};
    this.targetRate = opts.targetRate || 16000;
    this.ratio = Math.max(1, sampleRate / this.targetRate);
    this.chunkSize = Math.round((this.targetRate * (opts.chunkMs || 100)) / 1000);
    this.out = new Int16Array(this.chunkSize);
    this.outIdx = 0;
    this.acc = 0;
    this.accN = 0;
    this.pos = 0;
    this.levelSum = 0;
    this.levelN = 0;
    this.port.onmessage = (e) => {
      if (e.data && e.data.type === "flush") this.emit();
    };
  }

  process(inputs) {
    const input = inputs[0];
    const ch = input && input[0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      const s = ch[i];
      this.acc += s;
      this.accN += 1;
      this.levelSum += s * s;
      this.levelN += 1;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        this.push(this.acc / this.accN);
        this.acc = 0;
        this.accN = 0;
      }
    }
    return true;
  }

  push(v) {
    const c = v < -1 ? -1 : v > 1 ? 1 : v;
    this.out[this.outIdx++] = c < 0 ? c * 0x8000 : c * 0x7fff;
    if (this.outIdx >= this.chunkSize) this.emit();
  }

  emit() {
    if (this.outIdx === 0) return;
    const buffer = this.out.slice(0, this.outIdx).buffer;
    const level = Math.sqrt(this.levelSum / Math.max(1, this.levelN));
    this.outIdx = 0;
    this.levelSum = 0;
    this.levelN = 0;
    this.port.postMessage({ type: "chunk", buffer, level }, [buffer]);
  }
}

registerProcessor("pcm-recorder", PcmRecorderProcessor);
