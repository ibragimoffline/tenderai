-- =============================================================================
-- schema_patch_kod_pilot_atribut.sql  —  EKRAN va DARVOZA BIR XIL SANASIN
--
-- O'LCHANGAN MUAMMO (2026-09-03):
--
--   Kod navbati ekrani "Pilot: N/40 atama" ko'rsatadi. Bu raqam
--   `v_kod_pilot.atama_soni` dan, u esa `v_kod_qaror_olchov` dan
--   keladi va o'sha yerda shart shunchaki:
--
--       count(DISTINCT kalit) FILTER (WHERE qaror IS NOT NULL)
--
--   ATRIBUSIYA SHARTI YO'Q. Ya'ni `kompaniya_sessiyasi` (anonim) va
--   hatto `servis` (mashina) darajasidagi qarorlar ham sanalardi.
--
--   Sifat darvozasi (`v_sifat_darvoza`) esa FAQAT `aktorli` ni
--   (`erp_sessiya`, `aktor_elon`) sanaydi.
--
--   Natija: ko'ruvchi ekranda "40/40 bajarildi" ko'rib turgan holda
--   darvoza "0/40 TASDIQLANMAGAN" derdi. BIR NARSA UCHUN IKKI
--   RAQAM — va ekranga ishonilardi, chunki u ko'rinadigan joyda.
--
-- HOZIR ZARAR YO'Q: `kod_qaror` da 0 qator. Tuzatish AYNAN SHUNING
-- UCHUN hozir qilinadi — birinchi haqiqiy qarordan OLDIN.
--
-- NIMA O'ZGARADI: `v_kod_pilot` maqsadga sanaydigan raqamni
-- to'g'ridan-to'g'ri `kod_qaror` dan, DARVOZA BILAN AYNAN BIR XIL
-- shart bilan oladi. Atributsiz qarorlar YO'QOLMAYDI — ular
-- `atributsiz_qaror` ustunida ALOHIDA ko'rinadi.
--
-- `v_kod_qaror_olchov` TEGILMAYDI: u tahlil ko'rinishi (kelishuv,
-- qidiruv ulushi, vaqt) va u yerda barcha qarorlar o'rinli.
-- =============================================================================

\set ON_ERROR_STOP on

BEGIN;

CREATE OR REPLACE VIEW v_kod_pilot AS
SELECT c.id AS company_id,
       40 AS maqsad,
       -- MAQSADGA SANALADIGAN RAQAM — darvoza bilan bir xil shart.
       COALESCE(a.qaror_soni, 0::bigint)   AS qaror_soni,
       COALESCE(a.atama_soni, 0::bigint)   AS atama_soni,
       GREATEST(0::bigint, 40 - COALESCE(a.atama_soni, 0::bigint)) AS qolgan,
       COALESCE(o.olchangan, 0::bigint)    AS olchangan,
       COALESCE(o.dalilli_qaror, 0::bigint) AS dalilli,
       o.ortacha_sek,
       o.median_sek,
       o.taklif_kelishuv_foiz,
       o.qidiruv_foiz,
       (SELECT count(*) FROM v_catalog_kodsiz z
         WHERE z.company_id = c.id)        AS kodsiz_mahsulot,
       -- ATRIBUTSIZ qarorlar YASHIRILMAYDI, lekin maqsadga
       -- QO'SHILMAYDI. Ustun OXIRIDA turishi SHART:
       -- `CREATE OR REPLACE VIEW` yangi ustunni faqat oxiriga
       -- qo'shishga ruxsat beradi, o'rtaga qo'yilsa mavjud
       -- ustunni QAYTA NOMLASH deb o'qiydi va rad etadi.
       COALESCE(a.atributsiz_qaror, 0::bigint) AS atributsiz_qaror
  FROM company_account c
  LEFT JOIN v_kod_qaror_olchov o ON o.company_id = c.id
  LEFT JOIN (
      SELECT k.company_id,
             count(*) FILTER (
                 WHERE k.qaror IS NOT NULL
                   AND k.ishonch IN ('erp_sessiya', 'aktor_elon'))
                                                       AS qaror_soni,
             count(DISTINCT k.kalit) FILTER (
                 WHERE k.qaror IS NOT NULL
                   AND k.ishonch IN ('erp_sessiya', 'aktor_elon'))
                                                       AS atama_soni,
             count(*) FILTER (
                 WHERE k.qaror IS NOT NULL
                   AND (k.ishonch IS NULL
                        OR k.ishonch NOT IN ('erp_sessiya', 'aktor_elon')))
                                                       AS atributsiz_qaror
        FROM kod_qaror k
       GROUP BY k.company_id) a ON a.company_id = c.id;

COMMENT ON VIEW v_kod_pilot IS
    'Kod pilotining EKRANDAGI holati. `atama_soni` va `qaror_soni` '
    'FAQAT atributlangan qarorlarni sanaydi (`erp_sessiya`, '
    '`aktor_elon`) — `v_sifat_darvoza` bilan AYNAN bir xil shart, '
    'aks holda ekran va darvoza bir narsa uchun ikki raqam berardi. '
    'Atributsiz qarorlar `atributsiz_qaror` da ALOHIDA ko''rinadi.';

-- ---------------------------------------------------------------------
-- TEKSHIRUV — ekran va darvoza AYNAN mos kelsinmi
-- ---------------------------------------------------------------------
DO $$
DECLARE ekran BIGINT; darvoza BIGINT; cid INT;
BEGIN
    SELECT min(id) INTO cid FROM company_account WHERE active;
    IF cid IS NULL THEN
        RAISE NOTICE 'Faol ijarachi yo''q — taqqoslash o''tkazildi.';
        RETURN;
    END IF;
    SELECT qaror_soni INTO ekran   FROM v_kod_pilot     WHERE company_id = cid;
    SELECT aktorli    INTO darvoza FROM v_sifat_darvoza
     WHERE company_id = cid AND qatlam = 'kod_tasdigi';
    -- Ikkalasi BIR XIL hodisani sanaydi, lekin BOSHQA jadvaldan
    -- (`kod_qaror` va `catalog_product_code`). Teng bo'lishi SHART
    -- emas; shart — ikkalasi ham FAQAT atributlanganni sanashi.
    RAISE NOTICE 'ekran(kod_qaror)=%  darvoza(catalog_product_code)=%',
                 COALESCE(ekran, 0), COALESCE(darvoza, 0);
END $$;

COMMIT;


-- =============================================================================
-- ROLLBACK: schema_patch_kod_qaror_3.sql dagi `v_kod_pilot` blokini
--           `CREATE OR REPLACE` bilan qayta yurgizing.
-- =============================================================================
