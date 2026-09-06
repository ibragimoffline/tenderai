-- =============================================================================
-- schema_patch_kod_provenans.sql  —  "KODI BOR" va "ISHONCHLI KODI BOR"
--                                     BIR RAQAMDA TURMASIN
--
-- O'LCHANGAN MUAMMO (2026-09-03, company_id = 2):
--
--   v_catalog_kod_qamrov:
--       mahsulot           1 798
--       aniq_kod             467   -> aniq_foiz        25.97
--       keng_kod             581   -> har_qanday_foiz  58.29
--       kodsiz               750
--
--   Bu ikki foiz ANIQLIKNI (kod 8 belgimi yoki 5) o'lchaydi.
--   ISHONCHNI emas. Provenansni o'lchaganda manzara TESKARI chiqadi:
--
--       tasdiqlagan='tizim:auto', tasdiq_ishonch='servis'      467
--       tasdiqlagan='kompaniya',  tasdiq_ishonch='kuzatuvdan_oldin' 581
--       tasdiq_ishonch IN ('erp_sessiya','aktor_elon')           0
--       qaror_id IS NOT NULL (dalil havolasi)                    0
--       rad_etildi IS NOT NULL                                   0
--
--   Ya'ni `aniq_kod` — eng ishonchli to'plam kabi o'qiladi, aslida u
--   100% MASHINA qo'ygan (`servis`) va BIRORTASIDA inson tasdig'i
--   ham, dalil havolasi ham YO'Q. 581 tasi esa `kuzatuvdan_oldin` —
--   provenansi UMUMAN noma'lum.
--
--   "1 048 mahsulot tasdiqlangan" degan o'qish shu ikkisini bir
--   raqamga qo'shadi va INSON TASDIG'I bor deb tushuniladi.
--
-- YANGI ATAMA O'YLAB TOPILMADI. Sinflar mavjud kanonik lug'atdan
-- olinadi — `ishonch_yaroqli()` dagi besh daraja va
-- `tasdiqlandi`/`rad_etildi` ustunlari.
--
-- ANIQLIK va ISHONCH — IKKI O'LCHOV, va ular ALOHIDA ustunda
-- qoladi. Ularni ko'paytirib bitta ballga aylantirish aynan hozirgi
-- chalkashlikni qaytarardi.
-- =============================================================================

\set ON_ERROR_STOP on

BEGIN;

DROP VIEW IF EXISTS v_catalog_kod_provenans CASCADE;
CREATE VIEW v_catalog_kod_provenans AS
WITH kod AS (
    -- Mahsulotda BIR NECHA kod bo'lishi mumkin (o'lchandi: 379 tasida
    -- ikkitadan). Shuning uchun mahsulot ENG KUCHLI sinfi bo'yicha
    -- tasniflanadi — iyerarxiya PHASE 3 ning "ishonch tartibi".
    SELECT k.company_id,
           k.product_id,
           max(CASE
                 WHEN k.rad_etildi IS NOT NULL                   THEN 0
                 WHEN k.tasdiqlandi IS NULL                      THEN 1
                 WHEN k.tasdiq_ishonch = 'kuzatuvdan_oldin'      THEN 2
                 WHEN k.tasdiq_ishonch = 'servis'                THEN 3
                 WHEN k.tasdiq_ishonch = 'kompaniya_sessiyasi'   THEN 4
                 WHEN k.tasdiq_ishonch IN ('erp_sessiya','aktor_elon')
                                                                 THEN 5
                 ELSE 1
               END)                                       AS daraja,
           -- ANIQLIK — ALOHIDA o'lchov. 8 belgi = aniq tasniflagich
           -- kodi, 5 belgi = keng guruh. Ishonch bilan ARALASHTIRILMAYDI.
           bool_or(length(k.code) >= 8)                    AS aniq_kod_bor,
           bool_or(k.qaror_id IS NOT NULL)                 AS dalilli
      FROM catalog_product_code k
     GROUP BY k.company_id, k.product_id
)
SELECT p.company_id,
       count(*)                                                  AS mahsulot,
       -- --------------------------------------------------------------
       -- ISHONCH SINFLARI — o'zaro ISTISNO, yig'indi jamiga TENG
       -- --------------------------------------------------------------
       count(*) FILTER (WHERE k.product_id IS NULL)               AS kodsiz,
       count(*) FILTER (WHERE k.daraja = 0)                       AS rad_etilgan,
       count(*) FILTER (WHERE k.daraja = 1)                       AS nomzod,
       count(*) FILTER (WHERE k.daraja = 2)                       AS provenans_nomalum,
       count(*) FILTER (WHERE k.daraja = 3)                       AS mashina_tasdigi,
       count(*) FILTER (WHERE k.daraja = 4)                       AS anonim_tasdiq,
       count(*) FILTER (WHERE k.daraja = 5)                       AS inson_tasdigi,
       -- --------------------------------------------------------------
       -- ANIQLIK — MUSTAQIL o'lchov
       -- --------------------------------------------------------------
       count(*) FILTER (WHERE k.aniq_kod_bor)                     AS aniq_kodli,
       count(*) FILTER (WHERE k.product_id IS NOT NULL
                          AND NOT k.aniq_kod_bor)                 AS faqat_keng,
       count(*) FILTER (WHERE k.dalilli)                          AS dalilli,
       -- --------------------------------------------------------------
       -- FOIZLAR — HAR BIRI O'Z MAXRAJI BILAN, ARALASHTIRILMAYDI
       -- --------------------------------------------------------------
       round(100.0 * count(*) FILTER (WHERE k.product_id IS NOT NULL)
             / NULLIF(count(*), 0), 2)                            AS qamrov_foiz,
       round(100.0 * count(*) FILTER (WHERE k.daraja = 5)
             / NULLIF(count(*), 0), 2)                            AS inson_foiz,
       round(100.0 * count(*) FILTER (WHERE k.daraja >= 3)
             / NULLIF(count(*), 0), 2)                            AS tasdiqlangan_foiz
  FROM catalog_product p
  LEFT JOIN kod k ON k.company_id = p.company_id
                 AND k.product_id = p.id
 GROUP BY p.company_id;

COMMENT ON VIEW v_catalog_kod_provenans IS
    'Katalog kodlarining PROVENANSI. `qamrov_foiz` — "kodi bor"; '
    '`inson_foiz` — "INSON tasdiqlagan". Ikkisi BOSHQA narsa va hech '
    'qachon bitta raqamga qo''shilmaydi. `aniq_kodli` — ANIQLIK '
    'o''lchovi (8 belgili tasniflagich kodi), ISHONCH emas: '
    'o''lchandi (2026-09-03) — 467 ta "aniq" kodning HAMMASI '
    'mashina qo''ygan (`servis`) va birortasida inson tasdig''i yo''q.';


-- ---------------------------------------------------------------------
-- TEKSHIRUV — QOLDIQSIZ TOIFALASH
-- ---------------------------------------------------------------------
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN SELECT * FROM v_catalog_kod_provenans LOOP
        IF r.mahsulot <> r.kodsiz + r.rad_etilgan + r.nomzod
                        + r.provenans_nomalum + r.mashina_tasdigi
                        + r.anonim_tasdiq + r.inson_tasdigi THEN
            RAISE EXCEPTION
                'company %: mahsulot=% != sinflar yig''indisi',
                r.company_id, r.mahsulot;
        END IF;
    END LOOP;
    RAISE NOTICE 'TEKSHIRUV O''TDI — provenans sinflari qoldiqsiz.';
END $$;

COMMIT;


-- =============================================================================
-- ROLLBACK:  DROP VIEW IF EXISTS v_catalog_kod_provenans;
-- =============================================================================
