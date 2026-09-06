-- =============================================================================
-- schema_patch_hujjat_kashfi.sql   —   HUJJAT KASHFI BO'SHLIG'I KO'RINSIN
--
-- O'LCHANGAN MUAMMO (2026-09-03):
--
--     tender_document.discovered_at
--         xt-xarid   min = max = 2026-07-26      <- BITTA kun, 39 kun oldin
--         uzex       2026-07-26 .. 2026-09-03    <- uzluksiz
--
--     OCHIQ tenderlar
--         uzex       642 ta -> 642 tasida hujjat bor,   0 tasida yo'q
--         xt-xarid   148 ta ->   0 tasida hujjat bor, 148 tasida yo'q
--
-- Ya'ni xt-xarid hujjat kashfi (`etl_details.py`) dastlabki quyish kunidan
-- beri BIR MARTA HAM yurmagan. 148 ochiq tenderda nol hujjat -> nol talab
-- -> nol cheklist. Platforma amalda faqat metadata beradi.
--
-- NEGA 39 KUN KO'RINMADI — VA BU PATCH AYNAN SHUNI TUZATADI:
--
--     `v_document_processing_coverage` foizlarni `tender_document`
--     QATORLARI ustidan hisoblaydi. Hujjat qatori UMUMAN YO'Q tender
--     hech qanday maxrajga tushmaydi — 0/0 ko'rinmaydi. Shuning uchun
--     148 ta bo'sh tender turgan holda ham ko'rsatkich `68.6%` deb
--     sog'lom ko'rinardi.
--
--     Bu 9-sinf nuqson: skaner mezoni tor — obyekt RO'YXATGA TUSHMAYDI.
--     "Ko'radi-yu tanimaydi" emas, "umuman qaramaydi". Ikkinchisi
--     xavfliroq, chunki hech qanday soxta topilma ham chiqmaydi va
--     hammasi yashil ko'rinadi.
--
-- MEXANIZM tuzatishi (`etl_details.py` ni soatlik yurishga qaytarish) —
-- `run_etl.py` da. Bu patch faqat KO'RINISHNI qo'yadi. Ikkalasi kerak:
-- mexanizmni tuzatib o'lchovni qo'ymasak, keyingi safar boshqa qadam
-- jimgina o'chganda yana 39 kun ketadi.
--
-- QO'LLASH:
--     python migratsiya.py            (0073 sifatida manifestda)
--
-- Bog'liqlik: `schema_patch_doc_qamrov.sql` (holat lug'ati),
--             `schema_patch_kuzatuv.sql` (v_ops_holat — SHU YERDA
--             qayta yaratiladi, chunki yangi komponent qo'shiladi).
-- =============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- ---------------------------------------------------------------------
-- 1. HUJJAT QATORI YO'Q OCHIQ TENDERLAR
-- ---------------------------------------------------------------------
-- PLATFORMA RO'YXATI QAT'IY (`VALUES`), `GROUP BY source_platform` EMAS.
--
-- NEGA: agar platformada birorta ochiq tender qolmasa, `GROUP BY` o'sha
-- qatorni UMUMAN chiqarmaydi va operator ekranda satrni KO'RMAYDI —
-- buni "muammo yo'q" deb o'qirdi. Aynan shu xato `v_notify_saglik` da
-- bo'lgan va `schema_patch_kuzatuv.sql` da tuzatilgan; bu yerda uni
-- takrorlamaymiz.
--
-- MUHLAT (`kutilgan`): yangi ko'rilgan tenderda hujjat hali bo'lmasligi
-- NORMAL — `etl_details.py` `etl_tenders.py` dan KEYIN yuradi. Shuning
-- uchun foiz FAQAT 2 soatdan eski tenderlar ustidan hisoblanadi.
-- Soatlik yurishda 2 soat = kamida bitta to'liq imkoniyat o'tgan.
DROP VIEW IF EXISTS v_hujjatsiz_ochiq_tender CASCADE;
CREATE VIEW v_hujjatsiz_ochiq_tender AS
WITH ochiq AS (
    SELECT t.id,
           t.source_platform,
           t.first_seen_at,
           t.first_seen_at < now() - interval '2 hours'          AS kutilgan,
           EXISTS (SELECT 1 FROM tender_document d
                    WHERE d.tender_id = t.id)                    AS hujjati_bor
      FROM tender t
     WHERE t.status = 'open'
)
SELECT p.source_platform,
       count(o.id)                                               AS ochiq_tender,
       count(o.id) FILTER (WHERE o.kutilgan)                     AS kutilgan,
       count(o.id) FILTER (WHERE o.kutilgan AND o.hujjati_bor)   AS hujjatli,
       count(o.id) FILTER (WHERE o.kutilgan AND NOT o.hujjati_bor)
                                                                 AS hujjatsiz,
       -- MAXRAJ NOL BO'LSA `NULL`, `0` EMAS.
       -- "O'lchanmadi" ni "muammo yo'q" ga aylantirish — 8-qoida buzilishi.
       CASE WHEN count(o.id) FILTER (WHERE o.kutilgan) > 0
            THEN round(100.0 * count(o.id) FILTER (WHERE o.kutilgan
                                                     AND NOT o.hujjati_bor)
                     / count(o.id) FILTER (WHERE o.kutilgan), 1)
       END                                                       AS hujjatsiz_foiz,
       -- Eng uzoq kutib turgan bo'sh tender — "qachondan beri" savoli.
       round(EXTRACT(EPOCH FROM max(now() - o.first_seen_at)
                     FILTER (WHERE o.kutilgan AND NOT o.hujjati_bor))
             / 86400.0, 1)                                       AS eng_eski_kun,
       -- Kashfning O'ZI qachon oxirgi marta ishlagan. Bu ustun mexanizm
       -- o'chib qolganini FOIZDAN OLDIN ko'rsatadi: foiz sekin o'sadi,
       -- bu sana esa darhol qotib qoladi.
       (SELECT max(d.discovered_at) FROM tender_document d
         WHERE d.source_platform = p.source_platform)            AS oxirgi_kashf_at
  FROM (VALUES ('xt-xarid'), ('uzex')) AS p(source_platform)
  LEFT JOIN ochiq o ON o.source_platform = p.source_platform
 GROUP BY p.source_platform;

COMMENT ON VIEW v_hujjatsiz_ochiq_tender IS
    'OCHIQ tender bor, lekin `tender_document` da unga BIRORTA qator yo''q — '
    'hujjat kashfi (`etl_details.py` / `etl_uzex.py`) ishlamayotganining '
    'YAGONA to''g''ridan-to''g''ri belgisi. `v_document_processing_coverage` '
    'buni KO''RA OLMAYDI: u mavjud hujjat qatorlari ustidan hisoblaydi va '
    'nol qatorli tender maxrajga umuman tushmaydi. `hujjatsiz_foiz` NULL '
    'bo''lsa — o''lchanmadi (kutilgan tender yo''q), `0` EMAS.';

-- ---------------------------------------------------------------------
-- 2. OPERATOR KO'RINISHI — yangi komponent qo'shiladi
-- ---------------------------------------------------------------------
-- BU TA'RIF `schema_patch_kuzatuv.sql` (0072) DAGISINI ALMASHTIRADI.
-- Migratsiya tartibi bo'yicha eng oxirgi ta'rif amal qiladi; 0072 tarix
-- bo'lib qoladi. Ta'rif IKKI JOYDA SAQLANMAYDI — o'zgartirish kerak
-- bo'lsa ENG OXIRGI patchda qilinadi.
--
-- Farq: pastda `hujjat_kashfi` bloki qo'shildi. Qolgani 0072 dagidek.
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

-- HUJJAT KASHFI — 2026-09-03 da qo'shildi.
--
-- NEGA ALOHIDA KOMPONENT: pastdagi `hujjat_navbat` MAVJUD hujjat
-- qatorlarini sanaydi. Qator UMUMAN yaratilmasa u nolni ko'radi va
-- "navbat bo'sh, hammasi bajarilgan" deb o'qiladi. Kashf va navbat
-- BOSHQA-BOSHQA nosozliklar va chorasi ham boshqa.
SELECT 'hujjat_kashfi', source_platform,
       CASE WHEN kutilgan = 0            THEN 'nomalum'
            WHEN hujjatsiz_foiz >= 50    THEN 'xato'
            WHEN hujjatsiz_foiz > 0      THEN 'ogoh'
            ELSE 'ok' END,
       hujjatsiz_foiz,
       'hujjat qatori YO''Q ochiq tender, foiz'
  FROM v_hujjatsiz_ochiq_tender

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

-- ---------------------------------------------------------------------
-- 3. TEKSHIRUV — patch O'Z ISHINI QILGANINI ISBOTLASIN
-- ---------------------------------------------------------------------
-- "Xato chiqmadi" yetarli emas (2-sinf). Har ikki obyekt HAQIQATAN
-- so'rovga javob berishi va yangi komponent ko'rinishda BO'LISHI kerak.
DO $$
DECLARE n INT;
BEGIN
    SELECT count(*) INTO n FROM v_hujjatsiz_ochiq_tender;
    IF n <> 2 THEN
        RAISE EXCEPTION 'v_hujjatsiz_ochiq_tender % qator qaytardi, 2 kutilgan '
                        '(platforma ro''yxati QAT''IY)', n;
    END IF;

    SELECT count(*) INTO n FROM v_ops_holat WHERE komponent = 'hujjat_kashfi';
    IF n <> 2 THEN
        RAISE EXCEPTION 'v_ops_holat da hujjat_kashfi % qator, 2 kutilgan', n;
    END IF;

    RAISE NOTICE 'TEKSHIRUV O''TDI — hujjat kashfi endi KO''RINADI.';
END $$;

COMMIT;


-- =============================================================================
-- ROLLBACK:
--   DROP VIEW IF EXISTS v_ops_holat CASCADE;
--   DROP VIEW IF EXISTS v_hujjatsiz_ochiq_tender CASCADE;
--   -- so'ng schema_patch_kuzatuv.sql dagi v_ops_holat blokini qayta yurgizing
-- =============================================================================
