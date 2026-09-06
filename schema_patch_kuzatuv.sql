-- =============================================================================
-- KUZATUVCHANLIK — operator SQL yozmasdan javob olsin
--
--   psql "dbname=xtxarid user=postgres host=localhost" -f schema_patch_kuzatuv.sql
--
-- O'LCHANGAN BO'SHLIQLAR (2026-09-02)
-- -----------------------------------
-- Loyihada kuzatuvchanlikning katta qismi bor edi: struktura
-- jurnali (`api/jurnal.py`, sir niqoblash), `/health`, `/ready`,
-- `/freshness`, `v_etl_saglik`, hujjat va embedding ko'rinishlari,
-- `OnFailure=` ogohlantirishlari.
--
-- UCHTA SAVOLGA JAVOB YO'Q EDI:
--
--   1. "Bildirishnomalar yiqilyaptimi?"
--      `notify_sent` FAQAT muvaffaqiyatni yozadi. Xato jurnalga
--      chiqadi va SHU YERDA TUGAYDI -- ya'ni "necha marta
--      yiqildi" degan savolga baza javob bermaydi. Jurnalni
--      grep qilish operatorning ishi bo'lmasligi kerak.
--
--   2. "ETL osilib qoldimi?"
--      `etl_run.status='running'` qatorlari BOR va ular hech
--      qachon yopilmaydi. O'lchandi: 1089 va 1090 yurishlari
--      1.3 soatdan beri `running`, ammo YANGIROQ yurishlar
--      0.3 soat oldin muvaffaqiyatli tugagan. Ya'ni yetim
--      qatorlar to'planyapti va ular "ishlayapti" deb
--      ko'rinadi. `heartbeat_at` bor -- aniqlash mumkin edi,
--      lekin hech kim qaramasdi.
--
--   3. "Tizim sog'ligi qanday?"
--      Har kesim uchun ALOHIDA ko'rinish bor, lekin ularni
--      birlashtiradigan YAGONA javob yo'q edi. Operator o'nta
--      joyga qarashi kerak edi.
--
-- BU MIGRATSIYA `notify_sent` GA TEGMAYDI. U dedup kaliti
-- (bir tender -> bir kompaniyaga bir marta) va uni o'zgartirish
-- takroriy xabar yuborish xavfini tug'dirardi.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. BILDIRISHNOMA JURNALI — MUVAFFAQIYAT VA XATO BIR JOYDA
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notify_jurnal (
    id           bigserial PRIMARY KEY,
    company_id   integer     NOT NULL
                 REFERENCES company_account(id) ON DELETE CASCADE,
    kanal        text        NOT NULL,
    holat        text        NOT NULL,
    tender_id    bigint,
    xato_kod     text,
    -- XATO MATNI QISQARTIRILADI. To'liq SMTP javobi host, port va
    -- ba'zan foydalanuvchi nomini o'z ichiga oladi -- u jurnalga
    -- kerak, bazaga emas.
    xato_qisqa   text,
    urinish      integer     NOT NULL DEFAULT 1,
    at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT notify_jurnal_kanal_chk
        CHECK (kanal IN ('email', 'telegram')),
    CONSTRAINT notify_jurnal_holat_chk
        CHECK (holat IN ('yuborildi', 'yiqildi', 'otkazildi')),
    -- XATO HOLATIDA SABAB MAJBURIY. Aks holda "yiqildi" qatori
    -- sababsiz qolardi va u hech narsa bermasdi.
    CONSTRAINT notify_jurnal_sabab_chk
        CHECK (holat <> 'yiqildi' OR xato_kod IS NOT NULL),
    CONSTRAINT notify_jurnal_urinish_chk CHECK (urinish >= 1)
);

CREATE INDEX IF NOT EXISTS notify_jurnal_at_idx
    ON notify_jurnal (at DESC);
CREATE INDEX IF NOT EXISTS notify_jurnal_holat_idx
    ON notify_jurnal (holat, at DESC);

COMMENT ON TABLE notify_jurnal IS
    'Bildirishnoma urinishlari -- MUVAFFAQIYAT VA XATO. `notify_sent` '
    'dedup kaliti bo''lib qoladi va unga tegilmaydi.';

-- ---------------------------------------------------------------------------
-- 2. BILDIRISHNOMA SOG'LIGI
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS v_notify_saglik CASCADE;
CREATE VIEW v_notify_saglik AS
SELECT kanal,
       count(*) FILTER (WHERE at > now() - interval '24 hours') AS urinish_24s,
       count(*) FILTER (WHERE holat = 'yuborildi'
                          AND at > now() - interval '24 hours') AS yuborildi_24s,
       count(*) FILTER (WHERE holat = 'yiqildi'
                          AND at > now() - interval '24 hours') AS yiqildi_24s,
       count(*) FILTER (WHERE holat = 'yiqildi'
                          AND at > now() - interval '1 hour')   AS yiqildi_1s,
       COALESCE(sum(urinish - 1) FILTER (
           WHERE at > now() - interval '24 hours'), 0)          AS qayta_urinish_24s,
       max(at) FILTER (WHERE holat = 'yuborildi')               AS oxirgi_yuborildi,
       max(at) FILTER (WHERE holat = 'yiqildi')                 AS oxirgi_yiqildi,
       -- ULUSH FAQAT URINISH BO'LSA hisoblanadi. Nolga bo'lish
       -- o'rniga NULL -- "yiqilish yo'q" va "urinish yo'q"
       -- BOSHQA holatlar va ularni 0% deb birlashtirish
       -- yolg'on tinchlik berardi.
       CASE WHEN count(*) FILTER (WHERE at > now() - interval '24 hours') > 0
            THEN round(100.0 * count(*) FILTER (
                     WHERE holat = 'yiqildi'
                       AND at > now() - interval '24 hours')
                 / count(*) FILTER (WHERE at > now() - interval '24 hours'), 1)
       END AS yiqilish_foiz_24s
  FROM notify_jurnal
 GROUP BY kanal;

-- ---------------------------------------------------------------------------
-- 3. OSILIB QOLGAN ETL
-- ---------------------------------------------------------------------------
-- `heartbeat_at` -- ETL o'zi yangilab turadigan tirik belgisi.
-- U `started_at` dan MUHIMROQ: uzoq yuradigan yurish normal,
-- lekin YURAK URISHI TO'XTAGANI normal EMAS.
DROP VIEW IF EXISTS v_etl_osilgan CASCADE;
CREATE VIEW v_etl_osilgan AS
SELECT id,
       source_platform,
       started_at,
       heartbeat_at,
       round(EXTRACT(EPOCH FROM (now() - COALESCE(heartbeat_at,
                                                  started_at)))) AS jimlik_sek,
       round(EXTRACT(EPOCH FROM (now() - started_at)))            AS yosh_sek,
       processed, succeeded, failed
  FROM etl_run
 WHERE status = 'running';

COMMENT ON VIEW v_etl_osilgan IS
    'Hali `running` deb turgan yurishlar. `jimlik_sek` -- yurak '
    'urishidan beri o''tgan vaqt; chegara `api/kuzatuv.py` da.';

-- ---------------------------------------------------------------------------
-- 4. YAGONA OPERATOR KO'RINISHI
-- ---------------------------------------------------------------------------
-- HAR QATOR: bitta komponent, bitta holat, bitta o'lchov.
--
-- HOLAT UCH QIYMAT: `ok` | `ogoh` | `xato`. To'rtinchi qiymat
-- `nomalum` ATAYLAB BOR: o'lchov yo'q bo'lsa `ok` deb ko'rsatish
-- eng xavfli yolg'on bo'lardi -- operator "hammasi joyida" deb
-- o'qirdi, aslida HECH NARSA o'lchanmagan edi.
DROP VIEW IF EXISTS v_ops_holat CASCADE;
CREATE VIEW v_ops_holat AS
-- ETL yangiligi (manba bo'yicha)
SELECT 'etl_yangilik'::text                       AS komponent,
       source_platform                            AS kesim,
       CASE WHEN max(finished_at) IS NULL         THEN 'nomalum'
            WHEN max(finished_at) < now() - interval '6 hours'  THEN 'xato'
            WHEN max(finished_at) < now() - interval '3 hours'  THEN 'ogoh'
            ELSE 'ok' END                         AS holat,
       round(EXTRACT(EPOCH FROM (now() - max(finished_at))))::numeric AS qiymat,
       'oxirgi muvaffaqiyatli yurishdan beri, sekund'::text    AS olchov
  FROM etl_run
 WHERE status = 'ok'
 GROUP BY source_platform

UNION ALL

-- Osilib qolgan yurish
SELECT 'etl_osilgan', COALESCE(source_platform, '-'),
       CASE WHEN max(jimlik_sek) > 3600 THEN 'xato'
            WHEN max(jimlik_sek) > 1800 THEN 'ogoh'
            ELSE 'ok' END,
       max(jimlik_sek),
       'eng uzun jimlik, sekund'
  FROM v_etl_osilgan
 GROUP BY source_platform

UNION ALL

-- Hujjat navbati
-- HAQIQIY QIYMATLAR (o'lchandi): `navbatda` -- olishga
-- rejalashtirilgan; `rejalashtirilmagan` -- hali navbatga ham
-- qo'yilmagan (7 028 ta). IKKALASI HAM kutayotgan ish, lekin
-- ular ARALASHTIRILMAYDI: birinchisi ETL ning ishi, ikkinchisi
-- rejalashtirish bo'shlig'i va CHORASI BOSHQA.
SELECT 'hujjat_navbat', 'navbatda',
       CASE WHEN count(*) FILTER (WHERE holat = 'navbatda') > 5000 THEN 'ogoh'
            ELSE 'ok' END,
       count(*) FILTER (WHERE holat = 'navbatda')::numeric,
       'olishga navbatdagi hujjat'
  FROM v_document_state

UNION ALL

SELECT 'hujjat_navbat', 'rejalashtirilmagan',
       CASE WHEN count(*) FILTER (
                WHERE holat = 'rejalashtirilmagan') > 20000 THEN 'ogoh'
            ELSE 'ok' END,
       count(*) FILTER (WHERE holat = 'rejalashtirilmagan')::numeric,
       'hali rejalashtirilmagan hujjat'
  FROM v_document_state

UNION ALL

-- Embedding navbati
SELECT 'embedding_navbat', '-',
       CASE WHEN COALESCE(max(qamrov_foiz), 0) < 80 THEN 'ogoh'
            ELSE 'ok' END,
       round(COALESCE(max(qamrov_foiz), 0), 1),
       'qamrov, foiz'
  FROM v_embedding_coverage

UNION ALL

-- Bildirishnoma
-- KANAL RO'YXATI QAT'IY. Ilgari bu yerda `FROM v_notify_saglik`
-- turardi va jadval BO'SH bo'lsa QATOR UMUMAN CHIQMASDI --
-- operator ekranda bildirishnoma satrini KO'RMASDI va uni
-- "muammo yo'q" deb o'qirdi. O'LCHOVSIZLIK KO'RINISHI SHART.
SELECT 'bildirishnoma', k.kanal,
       CASE WHEN s.kanal IS NULL                    THEN 'nomalum'
            WHEN s.yiqildi_1s > 5                   THEN 'xato'
            WHEN COALESCE(s.yiqilish_foiz_24s, 0) > 20 THEN 'ogoh'
            ELSE 'ok' END,
       s.yiqilish_foiz_24s,
       'yiqilish ulushi 24s, foiz'
  FROM (VALUES ('email'), ('telegram')) AS k(kanal)
  LEFT JOIN v_notify_saglik s ON s.kanal = k.kanal

UNION ALL

-- Inson validatsiyasi (0070 dan) -- operatorga ham kerak: navbat
-- o'sib ketsa ish to'planib qolganini bildiradi.
SELECT 'korish_navbat', qatlam,
       CASE WHEN navbatda > 20000 THEN 'ogoh' ELSE 'ok' END,
       navbatda::numeric,
       'ko''rilmagan yozuv'
  FROM v_inson_dalil
 WHERE company_id = (SELECT min(id) FROM company_account WHERE active);

COMMENT ON VIEW v_ops_holat IS
    'Operator uchun YAGONA javob. `holat`: ok | ogoh | xato | '
    'nomalum. `nomalum` ATAYLAB bor -- o''lchovsizni `ok` deb '
    'ko''rsatish eng xavfli yolg''on.';

COMMIT;
