-- =============================================================================
-- schema_patch_pilot_avlod.sql  —  PILOT AVLODLARI: o'lik pilot yangisini
--                                   ABADIY to'sib turmasin
--
-- O'LCHANGAN MUAMMO (2026-09-03):
--
--     review_pilot (company_id = 2)      30 qator, 2026-08-26 da yaratilgan
--       hali ochiq tender                 8
--       eskirgan tender                  22
--       inson qarori berilgan             0
--
--     `requirement.pilot_yarat()` ning BIRINCHI qatori:
--
--         bor = SELECT count(*) FROM review_pilot WHERE company_id = ...
--         if bor:  return {"mavjud": True}      <-- ABADIY
--
--     Ya'ni bitta qator bo'lsa ham YANGI PILOT HECH QACHON yaratilmaydi.
--     Jadvalda holat ustuni UMUMAN YO'Q edi: `company_id, tender_id,
--     guruh, rejim, tartib, added_at`. Pilot "tugadi" yoki "eskirdi"
--     deb belgilanadigan joy yo'q.
--
--     Natijada yagona yo'l — tarixiy dalilni SQL bilan O'CHIRISH.
--     Bu namunani ham, "30 tenderda mediana" maxrajini ham yo'q qiladi.
--
-- YECHIM: AVLOD (generation). Har pilot o'z raqamini oladi, eskisi
-- JOYIDA QOLADI, yangisi ustiga qurilmaydi.
--
-- NEGA HOLAT SAQLANMAYDI, DALILDAN HOSIL BO'LADI:
--   Saqlangan `holat = 'faol'` vaqt o'tishi bilan HAQIQATDAN AJRALADI —
--   tenderlar yopiladi, hech kim jadvalni yangilamaydi va "faol" pilot
--   aslida o'lik bo'lib qoladi. Aynan shu sinf xato bu loyihada bir
--   necha marta chiqqan. Shuning uchun:
--
--     arxivlandi   — OPERATOR amali, saqlanadi (yagona saqlangan holat)
--     tugallandi   — HOSIL: har tenderda >= 1 ATRIBUTLANGAN inson qarori
--     eskirdi      — HOSIL: birorta tender ochiq emas, va tugallanmagan
--     faol         — qolgan hollarda
--
--   Yangi avlod FAQAT `faol` avlod bo'lmaganda yaratiladi.
-- =============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- ---------------------------------------------------------------------
-- 1. AVLOD raqami
-- ---------------------------------------------------------------------
ALTER TABLE review_pilot
    ADD COLUMN IF NOT EXISTS avlod INTEGER NOT NULL DEFAULT 1;

COMMENT ON COLUMN review_pilot.avlod IS
    'Pilot avlodi. Eski avlod O''CHIRILMAYDI — namuna va maxraj '
    'saqlanadi. Yangi avlod faqat `faol` avlod bo''lmaganda ochiladi.';

-- KALIT AVLODNI HAM QAMRAYDI. Busiz bir tender ikkinchi avlodga
-- tusha olmasdi va yangi pilot eskisining tenderlarini CHETLAB
-- o'tishga majbur bo'lardi — namuna qiyshayardi.
ALTER TABLE review_pilot DROP CONSTRAINT IF EXISTS review_pilot_pkey;
ALTER TABLE review_pilot
    ADD CONSTRAINT review_pilot_pkey PRIMARY KEY (company_id, avlod, tender_id);


-- ---------------------------------------------------------------------
-- 2. AVLOD REYESTRI — yaratilish va arxivlash FAKTI
-- ---------------------------------------------------------------------
-- Bu jadvalda FAQAT ikki fakt saqlanadi: qachon yaratildi va (agar
-- bo'lsa) qachon arxivlandi. Qolgan holatlar HOSIL BO'LADI.
CREATE TABLE IF NOT EXISTS review_pilot_avlod (
    company_id     INTEGER NOT NULL REFERENCES company_account(id)
                       ON DELETE CASCADE,
    avlod          INTEGER NOT NULL,
    yaratilgan_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    yaratgan       TEXT,                  -- aktor login yoki 'ko''chirish'
    arxivlandi_at  TIMESTAMPTZ,
    arxivlagan     TEXT,
    izoh           TEXT,
    PRIMARY KEY (company_id, avlod),
    CHECK (avlod >= 1),
    -- Arxivlash IKKI ustunni birga talab qiladi: "kim" siz "qachon"
    -- atributsiz qoladi va keyin uni tiklab bo'lmaydi.
    CHECK ((arxivlandi_at IS NULL AND arxivlagan IS NULL)
           OR (arxivlandi_at IS NOT NULL AND arxivlagan IS NOT NULL))
);

COMMENT ON TABLE review_pilot_avlod IS
    'Pilot avlodining YARATILISH va ARXIVLASH fakti. Boshqa holatlar '
    '(`tugallandi`, `eskirdi`, `faol`) SAQLANMAYDI — ular '
    '`v_pilot_avlod` da DALILDAN hisoblanadi, aks holda saqlangan '
    'holat vaqt o''tishi bilan haqiqatdan ajralib ketardi.';

-- Mavjud 30 qator uchun 1-avlod reyestri (idempotent).
INSERT INTO review_pilot_avlod (company_id, avlod, yaratilgan_at, yaratgan, izoh)
SELECT company_id, avlod, min(added_at), 'ko''chirish',
       'avlod mexanizmidan OLDIN yaratilgan pilot'
  FROM review_pilot
 GROUP BY company_id, avlod
ON CONFLICT (company_id, avlod) DO NOTHING;


-- ---------------------------------------------------------------------
-- 3. HOSIL QILINGAN HOLAT
-- ---------------------------------------------------------------------
DROP VIEW IF EXISTS v_pilot_avlod CASCADE;
CREATE VIEW v_pilot_avlod AS
WITH t AS (
    SELECT p.company_id,
           p.avlod,
           count(*)                                          AS tenderlar,
           count(*) FILTER (
               WHERE td.status = 'open'
                 AND (td.close_at IS NULL OR td.close_at > now()))
                                                             AS hali_ochiq,
           -- ATRIBUTLANGAN inson qarori — `ISHONCH_AKTORLI` bilan
           -- AYNAN bir xil ro'yxat. "Ko'rildi" yoki "ochildi" SANALMAYDI.
           count(*) FILTER (
               WHERE EXISTS (
                   SELECT 1 FROM tender_requirement r
                    WHERE r.tender_id = p.tender_id
                      AND r.company_id = p.company_id
                      AND r.review_status IN ('approved','rejected',
                                              'corrected','uncertain')
                      AND r.reviewed_ishonch IN ('erp_sessiya','aktor_elon')))
                                                             AS qarorli_tender
      FROM review_pilot p
      JOIN tender td ON td.id = p.tender_id
     GROUP BY p.company_id, p.avlod
)
SELECT a.company_id,
       a.avlod,
       a.yaratilgan_at,
       a.yaratgan,
       a.arxivlandi_at,
       COALESCE(t.tenderlar, 0)      AS tenderlar,
       COALESCE(t.hali_ochiq, 0)     AS hali_ochiq,
       COALESCE(t.qarorli_tender, 0) AS qarorli_tender,
       CASE
           WHEN a.arxivlandi_at IS NOT NULL              THEN 'arxivlandi'
           WHEN COALESCE(t.tenderlar, 0) = 0             THEN 'bosh'
           WHEN t.qarorli_tender >= t.tenderlar          THEN 'tugallandi'
           WHEN COALESCE(t.hali_ochiq, 0) = 0            THEN 'eskirdi'
           ELSE 'faol'
       END                            AS holat
  FROM review_pilot_avlod a
  LEFT JOIN t ON t.company_id = a.company_id AND t.avlod = a.avlod;

COMMENT ON VIEW v_pilot_avlod IS
    'Pilot avlodi va uning HOSIL QILINGAN holati: arxivlandi | '
    'tugallandi | eskirdi | faol | bosh. `qarorli_tender` FAQAT '
    'atributlangan inson qarorlarini sanaydi (`erp_sessiya`, '
    '`aktor_elon`) — ochish yoki ko''rish SANALMAYDI.';


-- ---------------------------------------------------------------------
-- 4. TEKSHIRUV
-- ---------------------------------------------------------------------
DO $$
DECLARE n INT; h TEXT;
BEGIN
    SELECT count(*) INTO n FROM review_pilot_avlod;
    IF n = 0 THEN
        RAISE NOTICE 'Pilot avlodlari yo''q — yangi baza.';
    ELSE
        SELECT holat INTO h FROM v_pilot_avlod
         WHERE company_id = (SELECT min(company_id) FROM review_pilot_avlod)
         ORDER BY avlod DESC LIMIT 1;
        RAISE NOTICE 'TEKSHIRUV: % avlod, oxirgisining holati = %', n, h;
    END IF;

    -- Har avlod REYESTRDA bo'lishi shart, aks holda `v_pilot_avlod`
    -- uni umuman ko'rmaydi va pilot "yo'q" bo'lib qoladi.
    SELECT count(*) INTO n FROM (
        SELECT DISTINCT company_id, avlod FROM review_pilot
        EXCEPT SELECT company_id, avlod FROM review_pilot_avlod) x;
    IF n > 0 THEN
        RAISE EXCEPTION '% ta avlod reyestrda YO''Q', n;
    END IF;
END $$;

COMMIT;


-- =============================================================================
-- ROLLBACK:
--   DROP VIEW IF EXISTS v_pilot_avlod CASCADE;
--   DROP TABLE IF EXISTS review_pilot_avlod;
--   ALTER TABLE review_pilot DROP CONSTRAINT review_pilot_pkey;
--   ALTER TABLE review_pilot ADD CONSTRAINT review_pilot_pkey
--       PRIMARY KEY (company_id, tender_id);
--   ALTER TABLE review_pilot DROP COLUMN avlod;
-- =============================================================================
