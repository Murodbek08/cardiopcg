#!/usr/bin/env node
// Synthetic phonocardiogram (PCG) WAV generator. NO real patient data: S1/S2-like sine bursts at ~75 bpm + light noise.
// Deterministic (seeded PRNG) so tests are reproducible.
//   node scripts/gen-wav.mjs [out.wav] [seconds] [sampleRate]
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export function makePcgWav({ seconds = 8, sampleRate = 4000, amp = 0.5, seed = 1 } = {}) {
  const n = Math.floor(seconds * sampleRate);
  const x = new Float64Array(n);
  let s = seed >>> 0;
  const rnd = () => { // mulberry32
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const burst = (start, freq, dur) => {
    const a = Math.floor(start * sampleRate);
    const len = Math.floor(dur * sampleRate);
    for (let i = 0; i < len && a + i < n; i++) {
      const hann = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (len - 1)));
      x[a + i] += Math.sin((2 * Math.PI * freq * i) / sampleRate) * hann;
    }
  };
  for (let beat = 0.2; beat < seconds - 0.5; beat += 0.8) {
    burst(beat, 60, 0.08); // S1
    burst(beat + 0.3, 80, 0.07); // S2
  }
  let peak = 1e-9;
  for (let i = 0; i < n; i++) peak = Math.max(peak, Math.abs(x[i]));
  const pcm = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) {
    const v = (x[i] / peak) * amp + (rnd() - 0.5) * 0.02;
    pcm.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(v * 32767))), i * 2);
  }
  const h = Buffer.alloc(44);
  h.write('RIFF', 0); h.writeUInt32LE(36 + pcm.length, 4); h.write('WAVE', 8);
  h.write('fmt ', 12); h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22);
  h.writeUInt32LE(sampleRate, 24); h.writeUInt32LE(sampleRate * 2, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34);
  h.write('data', 36); h.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([h, pcm]);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const here = dirname(fileURLToPath(import.meta.url));
  const out = resolve(process.argv[2] ?? resolve(here, '../fixtures/pcg-synthetic.wav'));
  const seconds = Number(process.argv[3] ?? 8);
  const sr = Number(process.argv[4] ?? 4000);
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, makePcgWav({ seconds, sampleRate: sr }));
  console.log(`wrote ${out} (${seconds}s @ ${sr} Hz, synthetic)`);
}
