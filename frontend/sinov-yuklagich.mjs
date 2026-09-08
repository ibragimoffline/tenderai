// =====================================================================
// TS SINOVLARINI YURGIZISH UCHUN YUKLAGICH
// =====================================================================
// MUAMMO. `src/*.test.ts` fayllari `node --experimental-strip-types`
// bilan yurar edi. Bu bayroq Node QANDAY QURILGANIGA bog'liq:
//
//     /usr/bin/node v22.22.1  ->  node_use_amaro = false
//     ERR_NO_TYPESCRIPT: Node.js is not compiled with TypeScript support
//
// Ya'ni sinovlar mezbon Node ikkiligining qurilish bayrog'iga
// bog'lanib qolgan edi. Reliz darvozasi aynan shu sababdan yiqildi.
//
// RAD ETILGAN YO'LLAR (o'lchov bilan)
// ===================================
// 1) `vite-node` — TEXNIK JIHATDAN ISHLAYDI (chiqish kodi ham
//    to'g'ri uzatiladi, o'lchandi). Rad etilishining sababi boshqa:
//    u fayllarni butun Vite quvuri orqali yurgizadi — plaginlar,
//    taxalluslar, `define` almashtirishlari bilan. Bu fayllar esa
//    ODDIY Node skriptlari va `tsc -b --noEmit` ularni shunday tip
//    tekshiruvidan o'tkazadi. Kelajakda kimdir Vite plagini
//    qo'shsa, sinovlarning xulqi JIMGINA o'zgarardi.
//
// 2) `tsc` bilan boshqa papkaga kompilyatsiya — sinovlar MA'NOSINI
//    o'zgartirardi: `colors.test.ts` va `xato.test.ts` manba
//    papkasini `import.meta.url` dan hisoblaydi va `index.css` ni
//    o'shandan o'qiydi. Papka skanerlash TS manbalar o'rniga
//    kompilyatsiya natijasini ko'rardi.
//
// 3) `module.registerHooks` (SINXRON) — Node 22.22.1 da CJS
//    bog'liqligini buzadi. O'lchandi: hech nima qilmaydigan,
//    BO'SH hook ham `jsdom` ni yiqitadi:
//        ERR_VM_MODULE_LINK_FAILURE: request for
//        './fallback/encoding.js' is from a module not been linked
//    `markdown.test.ts` esa `jsdom` ga tayanadi.
//
// TANLANGAN YO'L. `module.register()` — O'ZGARADIGAN YAGONA
// NARSA tiplarni olib tashlash usuli; qolgan hammasi oddiy Node
// bo'lib qoladi. Hooklar ALOHIDA ipda yuradi, shuning uchun (3)
// dagi CJS zanjiri buzilmaydi. Sinovning O'ZI esa asosiy ipda
// qoladi, shuning uchun:
//   * `process.exit(kod)` to'g'ridan-to'g'ri jarayon kodiga aylanadi;
//   * tashlangan xato yutilmaydi;
//   * `import.meta.url` ASL fayl yo'lini ko'rsatadi.
// =====================================================================
import { register } from 'node:module'

register('./sinov-hooklar.mjs', import.meta.url)
