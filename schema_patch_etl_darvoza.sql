-- =============================================================================
-- schema_patch_etl_darvoza.sql  —  ETL ISHONCHLILIGI: HOST va MANBA AJRATILADI
--
-- O'LCHANGAN MUAMMO (2026-09-03, oxirgi 7 kun, 128 yurish):
--
--     ok                      67
--     error                   57
--     running (osilgan)        5
--     partial                  1
--
--     57 xatodan:
--       uzildi                       41
--       sababsiz, LEKIN `error` matni AYNAN bir xil
--         ("jarayon majburan to'xtatilgan yoki kompyuter uxlagan")  12
--       error + terminal_reason='tugadi', matni yana o'sha            2
--       ------------------------------------------------------------
--       HOST UZILISHI                                               55  (96.5%)
--       MANBA XATOSI (manba_xato)                                    2  (3.5%)
--
--     Windows Task Scheduler tasdig'i: LastTaskResult = 0xC000013A
--     (STATUS_CONTROL_C_EXIT) — IKKALA vazifada ham, eng oxirgi
--     yurishda. Sabab: `LogonType=Interactive`.
--
-- BU PATCH NIMANI TUZATADI — O'LCHOV, MEXANIZM EMAS:
--
--   1. `v_etl_saglik` da HOST va MANBA ajratilmagan edi. `uzildi`
--      ustuni bor edi, lekin `manba_xato` yo'q — ya'ni "biz aybdormiz"
--      va "manba yiqildi" BIR XATO ustunida yig'ilardi. SRE qarori
--      esa ikkisida BUTUNLAY BOSHQA: birinchisi joylashtirishni
--      o'zgartirishni talab qiladi, ikkinchisi kutishni.
--
--   2. `ort_sek` MUVAFFAQIYATLI va UZILGAN yurishlarni bir o'rtachaga
--      qo'shardi. Natija (o'lchandi):
--
--          ort_sek (hammasi)     uzex  9 864 s   (~164 daqiqa)
--          ok yurishlar          uzex     31 s
--
--      Ya'ni ko'rsatkich "uzex ETL 2.7 soat davom etadi" deb
--      o'qilardi va SHU SEANSDA MENI AYNAN SHUNGA CHALG'ITDI.
--      Haqiqiy sog'lom yurish 31 SONIYA. Endi ikkisi ALOHIDA ustun.
--
--   3. Ishlab chiqarish maqsadi HECH QAYERDA yozilmagan edi.
--      `darvoza` ustuni uni MA'LUMOT DARAJASIDA qo'yadi.
--
-- MAQSAD (PHASE 7):
--     foydali_foiz >= 95    (ok + partial / jami)
--     host_uzildi   = 0
--     yurmoqda      = 0     (tushuntirilmagan `running` qolmasin)
--
-- Bog'liqlik: `schema_patch_etl_ishonch.sql` (0059) dagi `v_etl_saglik`
-- ta'rifini ALMASHTIRADI. Migratsiya tartibi bo'yicha eng oxirgisi
-- amal qiladi; ta'rif IKKI JOYDA SAQLANMAYDI.
-- =============================================================================

\set ON_ERROR_STOP on

BEGIN;

DROP VIEW IF EXISTS v_etl_saglik CASCADE;
CREATE VIEW v_etl_saglik AS
SELECT m.source_platform,
       count(*)                                                  AS yurish,
       count(*) FILTER (WHERE m.status = 'ok')                      AS ok,
       count(*) FILTER (WHERE m.status = 'partial')                 AS qisman,
       count(*) FILTER (WHERE m.status = 'error')                   AS xato,
       count(*) FILTER (WHERE m.status = 'running')                 AS yurmoqda,
       count(*) FILTER (WHERE m.terminal_reason = 'uzildi')         AS uzildi,

       -- ------------------------------------------------------------------
       -- HOST va MANBA — AJRATILGAN
       -- ------------------------------------------------------------------
       -- `terminal_reason` 2026-08-30 dan keyin to'ldirila boshlagan.
       -- Undan OLDINGI uzilishlarda ustun `NULL`, lekin `error` matni
       -- AYNAN bir xil. Matn bo'yicha tanish SHU SABABLI qo'shilgan —
       -- aks holda 12 ta haqiqiy host uzilishi "tasniflanmagan" bo'lib
       -- qolardi va host ulushi PAST ko'rinardi.
       count(*) FILTER (
           WHERE m.status = 'error'
             AND (m.terminal_reason = 'uzildi'
                  OR m.xato LIKE '%tugamasdan uzildi%')
       )                                                          AS host_uzildi,
       count(*) FILTER (
           WHERE m.status = 'error'
             AND m.terminal_reason = 'manba_xato'
             AND COALESCE(m.xato, '') NOT LIKE '%tugamasdan uzildi%'
       )                                                          AS manba_xato,
       -- QOLDIQSIZ TOIFALASH: xato = host + manba + tasniflanmagan.
       -- Uchinchi ustun ATAYLAB bor — nolga aylantirilmaydi.
       count(*) FILTER (
           WHERE m.status = 'error'
             AND m.terminal_reason IS DISTINCT FROM 'manba_xato'
             AND m.terminal_reason IS DISTINCT FROM 'uzildi'
             AND COALESCE(m.xato, '') NOT LIKE '%tugamasdan uzildi%'
       )                                                          AS tasniflanmagan,

       round(100.0 * count(*) FILTER (WHERE m.status IN ('ok', 'partial'))
             / NULLIF(count(*), 0), 1)                            AS foydali_foiz,

       -- ------------------------------------------------------------------
       -- DAVOMIYLIK — SOG'LOM va UZILGAN ARALASHTIRILMAYDI
       -- ------------------------------------------------------------------
       round(avg(m.davomiylik_sek) FILTER (WHERE m.davomiylik_sek IS NOT NULL), 1)
                                                                  AS ort_sek,
       -- ASOSIY RAQAM: quvur SOG'LOM bo'lganda qancha davom etadi.
       round(avg(m.davomiylik_sek) FILTER (
                 WHERE m.davomiylik_sek IS NOT NULL
                   AND m.status IN ('ok', 'partial')), 1)           AS ort_sek_ok,
       round((percentile_cont(0.95) WITHIN GROUP (ORDER BY m.davomiylik_sek)
              FILTER (WHERE m.davomiylik_sek IS NOT NULL
                        AND m.status IN ('ok', 'partial')))::numeric, 1)
                                                                  AS p95_sek_ok,

       count(*) FILTER (WHERE m.davomiylik_sek IS NULL
                          AND m.status <> 'running')                AS olchovsiz,
       sum(m.succeeded)                                             AS jami_yozildi,
       sum(m.failed)                                                AS jami_yiqildi,
       sum(m.retried)                                               AS jami_qayta_urinish,
       sum(m.skipped)                                               AS jami_otkazildi,

       -- ------------------------------------------------------------------
       -- ISHLAB CHIQARISH DARVOZASI (PHASE 7)
       -- ------------------------------------------------------------------
       -- Maqsad MA'LUMOTDA yoziladi, hujjatda emas: hujjat o'qilmaydi.
       -- `nomalum` ATAYLAB bor — yurish bo'lmasa "ochiq" deb ko'rsatish
       -- o'lchovsizni muvaffaqiyat deb ko'rsatish bo'lardi.
       CASE
           WHEN count(*) = 0                                  THEN 'nomalum'
           WHEN count(*) FILTER (
                    WHERE m.status = 'error'
                      AND (m.terminal_reason = 'uzildi'
                           OR m.xato LIKE '%tugamasdan uzildi%')) > 0
                                                              THEN 'host_uziladi'
           WHEN count(*) FILTER (WHERE m.status = 'running') > 0 THEN 'osilgan_bor'
           WHEN round(100.0 * count(*) FILTER (WHERE m.status IN ('ok','partial'))
                      / NULLIF(count(*), 0), 1) >= 95          THEN 'ochiq'
           ELSE 'yopiq'
       END                                                        AS darvoza
  FROM v_etl_run_olchov m
 WHERE m.started_at > now() - interval '7 days'
 GROUP BY m.source_platform;

COMMENT ON VIEW v_etl_saglik IS
    'ETL ishonchliligi, 7 kun. `host_uzildi` va `manba_xato` ATAYLAB '
    'ajratilgan: birinchisi joylashtirishni o''zgartirishni talab qiladi, '
    'ikkinchisi kutishni. `ort_sek` uzilganlarni ham qo''shadi va SHU '
    'SABABLI chalg''ituvchi — sog''lom quvur uchun `ort_sek_ok` ni o''qing. '
    '`darvoza`: ochiq | yopiq | host_uziladi | osilgan_bor | nomalum. '
    'Maqsad: foydali_foiz >= 95, host_uzildi = 0, yurmoqda = 0.';

-- ---------------------------------------------------------------------
-- TEKSHIRUV — patch O'Z ISHINI QILGANINI ISBOTLASIN
-- ---------------------------------------------------------------------
DO $$
DECLARE r RECORD; n INT := 0;
BEGIN
    FOR r IN SELECT * FROM v_etl_saglik LOOP
        n := n + 1;
        -- QOLDIQSIZ TOIFALASH: xato yig'indisi mos kelsin.
        IF r.xato <> r.host_uzildi + r.manba_xato + r.tasniflanmagan THEN
            RAISE EXCEPTION
                '% : xato=% != host=% + manba=% + tasniflanmagan=%',
                r.source_platform, r.xato, r.host_uzildi, r.manba_xato,
                r.tasniflanmagan;
        END IF;
        IF r.darvoza NOT IN ('ochiq','yopiq','host_uziladi','osilgan_bor',
                             'nomalum') THEN
            RAISE EXCEPTION 'darvoza lug''atdan tashqarida: %', r.darvoza;
        END IF;
    END LOOP;
    IF n = 0 THEN
        RAISE NOTICE 'v_etl_saglik BO''SH — 7 kunda yurish yo''q.';
    ELSE
        RAISE NOTICE 'TEKSHIRUV O''TDI — % platforma, toifalash qoldiqsiz.', n;
    END IF;
END $$;

COMMIT;


-- =============================================================================
-- ROLLBACK:
--   DROP VIEW IF EXISTS v_etl_saglik CASCADE;
--   -- so'ng schema_patch_etl_ishonch.sql dagi v_etl_saglik blokini qayta yurgizing
-- =============================================================================
