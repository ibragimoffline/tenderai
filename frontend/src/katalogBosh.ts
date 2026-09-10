/**
 * "SIZGA MOS" BO'SH BO'LGANDA — SABABI AYTILADI.
 *
 * O'LCHANGAN NUQSON (2026-09-10, ishlab chiqarish): kompaniya
 * katalogiga 1 796 ta mahsulot qo'shilgan edi, `tender_good` da
 * 2 491 ta kodli qator bor edi, lekin `dim_good_code` lug'ati BO'SH
 * edi — ya'ni kod taklif qilish umuman ishlamagan. Natijada
 * "Sizga mos" bo'sh chiqdi va foydalanuvchiga:
 *
 *     Topilmadi
 *     Filtrlarni o'zgartirib ko'ring.
 *
 * deb yozildi. Bu YOLG'ON MASLAHAT: filtrning hech qanday aloqasi
 * yo'q edi, katalog KODLANMAGAN edi. Foydalanuvchi filtr bilan
 * ovora bo'ladi va tizim ishlamayapti deb xulosa qiladi — salbiy
 * shartdan olingan xato xulosa.
 *
 * Shu sababli bo'shlikning SABABI backenddan keladi
 * (`/catalog/match` -> `holat`, `api/kodlash.py:holat()`) va bu yerda
 * AYNAN BITTA holatga aylantiriladi. Funksiya SOF: render yo'q,
 * shuning uchun beshala holat runner'siz sinaladi
 * (`katalogBosh.test.ts`).
 */
import type { KodlashHolat } from './types'
import type { TKey, TVars } from './i18n-core'

export type KatalogBoshKalit =
  /** Katalog umuman bo'sh — birinchi qadam mahsulot qo'shish. */
  | 'mahsulot_yoq'
  /** Mahsulot bor, kodlangani YO'Q va tasdiqqa taklif ham yo'q. */
  | 'kodsiz'
  /** Kodlangani yo'q, lekin tasdiq kutayotgan takliflar bor. */
  | 'taklif_kutmoqda'
  /** Bir qismi kodlangan — moslik topilmadi, lekin qamrov to'liq emas. */
  | 'qisman'
  /** To'liq kodlangan — moslik CHINAKAM yo'q. */
  | 'moslik_yoq'
  /** Holat KELMADI. Hech qanday sabab da'vo qilinmaydi. */
  | 'olchanmadi'

export interface KatalogBosh {
  kalit: KatalogBoshKalit
  sarlavha: TKey
  izoh: TKey
  vars?: TVars
  /**
   * Filtr maslahati BERILADIMI.
   *
   * Faqat qamrov to'liq bo'lganda `true`: shundagina bo'shlikning
   * qolgan sababi rostdan ham filtr bo'lishi mumkin. Kodlanmagan
   * katalogda bu maslahat ODAMNI ADASHTIRADI va u BERILMAYDI.
   */
  filtrMaslahati: boolean
}

export function katalogBoshHolat(
  holat: KodlashHolat | null | undefined,
): KatalogBosh {
  // O'LCHANMAGAN — NOL EMAS. Eski javob (yoki tarmoq xatosi) `holat`
  // bermaydi; unda sabab haqida jim turamiz va eski umumiy matn
  // qoladi. Yolg'on sabab aytishdan ko'ra hech narsa aytmaslik afzal.
  if (!holat) {
    return {
      kalit: 'olchanmadi',
      sarlavha: 'common.notFound',
      izoh: 'table.empty',
      filtrMaslahati: true,
    }
  }

  const mahsulot = holat.mahsulot ?? 0
  const kodlangan = holat.kodlangan ?? 0
  const kutayotgan = holat.kutayotgan_taklif ?? 0
  const kodsiz = holat.kodsiz ?? Math.max(mahsulot - kodlangan, 0)

  if (mahsulot === 0) {
    return {
      kalit: 'mahsulot_yoq',
      sarlavha: 'match.emptyNoProducts',
      izoh: 'match.emptyNoProductsBody',
      filtrMaslahati: false,
    }
  }

  if (kodlangan === 0) {
    // TASDIQ KUTAYOTGAN TAKLIF — bu BOSHQA holat va keyingi qadami
    // ham boshqa: odam tasdiqlashi kerak, kutish emas.
    if (kutayotgan > 0) {
      return {
        kalit: 'taklif_kutmoqda',
        sarlavha: 'match.emptyPending',
        izoh: 'match.emptyPendingBody',
        vars: { n: kutayotgan },
        filtrMaslahati: false,
      }
    }
    return {
      kalit: 'kodsiz',
      sarlavha: 'match.emptyUncoded',
      izoh: 'match.emptyUncodedBody',
      vars: { n: mahsulot },
      filtrMaslahati: false,
    }
  }

  if (kodsiz > 0) {
    return {
      kalit: 'qisman',
      sarlavha: 'match.emptyPartial',
      izoh: 'match.emptyPartialBody',
      vars: { n: kodsiz, jami: mahsulot },
      filtrMaslahati: false,
    }
  }

  // To'liq kodlangan: bo'shlik CHINAKAM natija.
  return {
    kalit: 'moslik_yoq',
    sarlavha: 'match.emptyNoMatch',
    izoh: 'match.emptyNoMatchBody',
    filtrMaslahati: true,
  }
}
