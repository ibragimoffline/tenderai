// =====================================================================
// TS SINOVLARI UCHUN YUKLASH HOOKLARI (alohida ipda yuradi)
// =====================================================================
// Bu fayl `sinov-yuklagich.mjs` orqali `module.register()` bilan
// ro'yxatdan o'tadi. Sababi `sinov-yuklagich.mjs` da yozilgan.
//
// FAQAT tiplarni olib tashlaydi. Tip TEKSHIRUVI `tsc -b --noEmit`
// ning ishi va u darvozada alohida yuradi.
// =====================================================================
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { transformSync } from 'esbuild'

const TS = /\.(?:m|c)?tsx?$/

export async function load(url, context, nextLoad) {
  if (!url.startsWith('file:') || !TS.test(new URL(url).pathname)) {
    return nextLoad(url, context)
  }
  const yol = fileURLToPath(url)
  const { code } = transformSync(readFileSync(yol, 'utf8'), {
    loader: yol.endsWith('x') ? 'tsx' : 'ts',
    format: 'esm',
    target: 'node22',
    sourcefile: yol,
    sourcemap: 'inline',
  })
  return { format: 'module', shortCircuit: true, source: code }
}
