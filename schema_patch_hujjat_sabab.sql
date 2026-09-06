-- =============================================================================
-- schema_patch_hujjat_sabab.sql  —  "REJALASHTIRILMAGAN" ENDI SABABI BILAN
--
-- MUAMMO: `tender_document.holat = 'rejalashtirilmagan'` — 7 028 qator —
-- BITTA UMUMIY QOP edi. U "nega" degan savolga javob bermasdi, va
-- javobsiz qop ikki xil narsani yashiradi:
--
--     * QARORGA KERAKMAS hujjat (tender yakunlangan) — bu NORMAL;
--     * QARORGA KERAK hujjat, lekin quvur uni ko'rmayapti — bu NUQSON.
--
-- Ikkalasi bir raqamda turganda birinchisi ikkinchisini BEKITADI.
-- O'lchandi (2026-09-03):
--
--     tender_yakunlangan   6 977   (cancel/close/expired/not_realized)
--     tender_jarayonda        51   (check_docs, quality_checking,
--                                   commercial_checking, tech_checking,
--                                   objections_summary)
--     tender_yoq               0
--     sabab_nomalum            0
--
-- 51 ta hujjat BAHOLASH bosqichidagi tenderga tegishli — ular
-- "yakunlangan" EMAS. Bu qopda ular ko'rinmasdi.
--
-- NEGA QATTIQ RO'YXAT YOZILMAYDI: sabab `dim_status.is_terminal` dan
-- KELIB CHIQADI. Manba yangi status qo'shsa u avtomatik to'g'ri
-- toifaga tushadi. Qattiq yozilgan ro'yxat esa jimgina eskirardi —
-- bu loyihada aynan shu sinf xato bir necha marta takrorlangan.
--
-- `sabab_nomalum` ATAYLAB bor va u NOLGA AYLANTIRILMAYDI: lug'atda
-- yo'q status paydo bo'lsa u KO'RINISHI kerak, "yakunlangan" deb
-- yutib yuborilmasligi kerak.
--
-- Bog'liqlik: `schema_patch_doc_qamrov.sql` dagi `v_document_state`
-- ta'rifini ALMASHTIRADI (ustun QO'SHILADI, mavjudlari o'zgarmaydi —
-- `v_document_processing_coverage` va `v_ops_holat` buzilmaydi).
-- =============================================================================

\set ON_ERROR_STOP on

BEGIN;

DROP VIEW IF EXISTS v_document_qamrov_sabab CASCADE;

-- `CREATE OR REPLACE`, `DROP ... CASCADE` EMAS.
--
-- NEGA MUHIM: `v_document_state` ga `v_document_processing_coverage`
-- va `v_ops_holat` bog'langan. `CASCADE` ularni JIMGINA olib
-- ketardi va patch "OK" deb tugardi — operator ekrani esa bo'sh
-- qolardi. `REPLACE` yangi ustunni OXIRIGA qo'shishga ruxsat beradi,
-- mavjud ustunlar nomi/turi/tartibi o'zgarmasa. `sabab` aynan
-- oxirida turibdi.
CREATE OR REPLACE VIEW v_document_state AS
SELECT COALESCE(d.tender_id, t.tender_id)                    AS tender_id,
       COALESCE(d.file_ref, t.file_ref)                      AS file_ref,
       d.source_platform,
       d.file_type,
       d.size_bytes,
       CASE WHEN d.tender_id IS NULL THEN 'metadata_yoqolgan'
            ELSE d.holat END                                 AS holat,
       d.urinish,
       d.discovered_at,
       d.download_started_at,
       d.downloaded_at,
       d.extraction_started_at,
       COALESCE(d.extraction_finished_at, t.extracted_at)    AS extraction_finished_at,
       d.last_error_at,
       COALESCE(d.last_error, t.error)                       AS last_error,
       t.status                                              AS matn_status,
       t.char_count,
       (t.tender_id IS NOT NULL)                             AS matn_qatori_bor,

       -- ------------------------------------------------------------------
       -- SABAB — "nega qamrovda emas". HAR QATOR uchun to'ldiriladi.
       -- ------------------------------------------------------------------
       CASE
           WHEN d.tender_id IS NULL              THEN 'metadata_yoqolgan'
           WHEN d.holat <> 'rejalashtirilmagan'  THEN 'qamrovda'
           WHEN tt.id IS NULL                    THEN 'tender_yoq'
           WHEN ds.status_code IS NULL           THEN 'sabab_nomalum'
           WHEN ds.is_terminal                   THEN 'tender_yakunlangan'
           WHEN tt.status = 'open'
                AND tt.close_at IS NOT NULL
                AND tt.close_at <= now()         THEN 'muddati_otgan'
           ELSE 'tender_jarayonda'
       END                                                   AS sabab
  FROM tender_document d
  FULL JOIN tender_document_text t
         ON t.tender_id = d.tender_id AND t.file_ref = d.file_ref
  LEFT JOIN tender tt      ON tt.id = d.tender_id
  LEFT JOIN dim_status ds  ON ds.status_code = tt.status AND ds.domain = 'tender';

COMMENT ON VIEW v_document_state IS
    'Hujjatning QAYTA ISHLASH bosqichi (`holat`) va — qamrovda '
    'bo''lmasa — SABABI (`sabab`). `sabab` `dim_status.is_terminal` dan '
    'kelib chiqadi, qattiq ro''yxatdan emas: manba yangi status '
    'qo''shsa u avtomatik to''g''ri toifaga tushadi. `sabab_nomalum` '
    'NOLGA AYLANTIRILMAYDI — lug''atsiz status KO''RINISHI shart.';


-- ---------------------------------------------------------------------
-- QAMROV: platforma x holat x sabab — QOLDIQSIZ
-- ---------------------------------------------------------------------
CREATE VIEW v_document_qamrov_sabab AS
SELECT COALESCE(source_platform, '(metadata yo''q)')  AS source_platform,
       holat,
       sabab,
       count(*)                                       AS n,
       count(*) FILTER (WHERE matn_qatori_bor)         AS matn_bor,
       round(sum(COALESCE(size_bytes, 0)) / 1048576.0, 1) AS mb
  FROM v_document_state
 GROUP BY 1, 2, 3;

COMMENT ON VIEW v_document_qamrov_sabab IS
    'Har hujjat AYNAN BITTA (platforma, holat, sabab) uchligiga tushadi. '
    'Yig''indi `tender_document` + yetim matn qatorlari soniga TENG — '
    'buni `_tests/doc_qamrov_test.py` tekshiradi.';


-- ---------------------------------------------------------------------
-- TEKSHIRUV
-- ---------------------------------------------------------------------
DO $$
DECLARE jami INT; qop INT; nomalum INT; yigindi INT;
BEGIN
    SELECT count(*) INTO jami FROM v_document_state;
    SELECT COALESCE(sum(n), 0) INTO yigindi FROM v_document_qamrov_sabab;
    IF jami <> yigindi THEN
        RAISE EXCEPTION 'QOLDIQ: v_document_state=% != qamrov yig''indisi=%',
                        jami, yigindi;
    END IF;

    SELECT count(*) INTO qop FROM v_document_state WHERE sabab IS NULL;
    IF qop <> 0 THEN
        RAISE EXCEPTION '% qatorda `sabab` NULL — har qator sababli bo''lishi shart',
                        qop;
    END IF;

    SELECT count(*) INTO nomalum FROM v_document_state
     WHERE sabab = 'sabab_nomalum';
    IF nomalum > 0 THEN
        RAISE WARNING '% ta hujjat LUG''ATSIZ statusli tenderga tegishli — '
                      '`dim_status` to''ldirilishi kerak', nomalum;
    END IF;

    RAISE NOTICE 'TEKSHIRUV O''TDI — % qator, hammasi sababli.', jami;
END $$;

COMMIT;


-- =============================================================================
-- ROLLBACK:
--   DROP VIEW IF EXISTS v_document_qamrov_sabab;
--   -- so'ng schema_patch_doc_qamrov.sql dagi v_document_state blokini
--   -- CREATE OR REPLACE bilan qayta yurgizing (bog'liq ko'rinishlar
--   -- tegilmaydi).
-- =============================================================================
