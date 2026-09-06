-- =============================================================================
-- INSON TASDIG'I — DALIL BILAN, YORLIQ BILAN EMAS
--
--   psql "dbname=xtxarid user=postgres host=localhost" -f schema_patch_inson_dalil.sql
--
-- O'LCHANGAN NUQSON (2026-09-02)
-- ------------------------------
-- 0068-migratsiya inson halqasi "notekis, lekin bo'sh emas" deb
-- xulosa qildi va u BITTA raqamga tayandi:
--
--     kod tasdig'i   1 048 / 1 427   73.4%
--
-- Bu raqam TEKSHIRILDI va u INSON QARORI EMAS:
--
--     tasdiqlagan     qator   turli sekund   tezlik
--     kompaniya         581              2   ~290 qator/sek
--     tizim:auto        467             14    ~34 qator/sek
--     --------------------------------------------------
--     jami            1 048             16
--
-- 1 048 ta "tasdiq" atigi 16 ta turli sekundda sodir bo'lgan.
-- Ikkala tezlik ham inson uchun mumkin emas. Ustiga:
--
--   * `tasdiqlagan` da atigi IKKI xil qiymat bor va ikkalasi ham
--     odam nomi emas ('tizim:auto' — so'zma-so'z "tizim");
--   * 1 048 tasining HAMMASIDA `qaror_id IS NULL`, ya'ni hech
--     biri `kod_qaror` dagi inson qaroriga bog'lanmagan;
--   * `kod_qaror` jadvalining O'ZIDA 0 ta qator bor.
--
-- Ya'ni MASHINA CHIQISHI INSON TASDIG'I sifatida ko'rsatilgan edi
-- va u tayyorlik hisobotiga 73.4% bo'lib chiqqan.
--
-- QANDAY YUZ BERDI: IKKI YO'L
-- ---------------------------
-- Kodlashda ikkita yozuv yo'li bor edi:
--
--   /kod/qaror                    -> kod_qaror (aktor, ishonch, audit)
--   /catalog/{id}/kod-tasdiq      -> catalog_product_code (faqat MATN)
--
-- Ikkinchisi `kim` ustuniga ISTALGAN bo'sh bo'lmagan satrni qabul
-- qilardi. "Bo'sh bo'lmagan satr" — bu odam degani EMAS. Bazadagi
-- yagona qo'riqchi (`catalog_product_code_tasdiq_odam`) aynan shu
-- kuchsiz shartni tekshirardi.
--
-- BU MIGRATSIYA NIMA QILADI
-- -------------------------
--   1. MA'LUMOTNI O'CHIRMAYDI. 1 048 bog'lanish joyida qoladi va
--      moslashtirish avvalgidek ishlaydi — ular YAROQSIZ emas,
--      ular INSON QARORI EMAS, xolos.
--   2. Har tasdiqqa MANBA yozadi (`tasdiq_ishonch`), ya'ni
--      "kim tasdiqladi" savoli endi javobsiz qolmaydi.
--   3. Inson tasdig'ini BAZA DARAJASIDA majburlaydi: aktor + vaqt.
--   4. Hisoblagichni HALOL qiladi — mashina qatorlari inson
--      ulushiga KIRMAYDI.
--
-- UNKNOWN — UNKNOWN BO'LIB QOLADI: 581 ta ommaviy import qatoriga
-- "mashina" deb ham yozilmaydi, chunki uning manbasi ANIQ EMAS.
-- Ular `kuzatuvdan_oldin` deb belgilanadi — loyihaning mavjud
-- "manbasi noma'lum" yorlig'i.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. TASDIQ MANBASI — ustunlar
-- ---------------------------------------------------------------------------
ALTER TABLE catalog_product_code
    ADD COLUMN IF NOT EXISTS tasdiq_ishonch  text,
    ADD COLUMN IF NOT EXISTS tasdiq_actor_id bigint;

COMMENT ON COLUMN catalog_product_code.tasdiq_ishonch IS
    'Tasdiq/rad MANBASI. erp_sessiya|aktor_elon = aktorli inson; '
    'kompaniya_sessiyasi = inson, lekin shaxsan aniqlanmagan; '
    'servis|kuzatuvdan_oldin = INSON EMAS.';

-- ---------------------------------------------------------------------------
-- 2. MAVJUD MA'LUMOTNI YARASHTIRISH (o'chirmasdan)
-- ---------------------------------------------------------------------------
-- 'tizim:auto' — manbasi ANIQ: avtomatik skript. `servis`.
UPDATE catalog_product_code
   SET tasdiq_ishonch = 'servis'
 WHERE tasdiqlandi IS NOT NULL
   AND tasdiq_ishonch IS NULL
   AND tasdiqlagan = 'tizim:auto';

-- 'kompaniya' — ommaviy import. Odam bosgan bo'lishi ham mumkin,
-- skript bo'lishi ham. TAXMIN QILMAYMIZ.
UPDATE catalog_product_code
   SET tasdiq_ishonch = 'kuzatuvdan_oldin'
 WHERE tasdiqlandi IS NOT NULL
   AND tasdiq_ishonch IS NULL;

UPDATE catalog_product_code
   SET tasdiq_ishonch = 'kuzatuvdan_oldin'
 WHERE rad_etildi IS NOT NULL
   AND tasdiq_ishonch IS NULL;

-- ---------------------------------------------------------------------------
-- 3. QO'RIQCHILAR — bundan keyin manbasiz tasdiq YOZILMAYDI
-- ---------------------------------------------------------------------------
ALTER TABLE catalog_product_code
    DROP CONSTRAINT IF EXISTS catalog_product_code_tasdiq_manba_chk;
ALTER TABLE catalog_product_code
    ADD CONSTRAINT catalog_product_code_tasdiq_manba_chk CHECK (
        (tasdiqlandi IS NULL AND rad_etildi IS NULL)
        OR (tasdiq_ishonch IS NOT NULL AND ishonch_yaroqli(tasdiq_ishonch))
    );

-- AKTOR IZCHILLIGI — `tender_requirement` va `tender_routing`
-- dagi bilan AYNI qoida (bitta manba, ikkita nusxa emas).
ALTER TABLE catalog_product_code
    DROP CONSTRAINT IF EXISTS catalog_product_code_aktor_izchil_chk;
ALTER TABLE catalog_product_code
    ADD CONSTRAINT catalog_product_code_aktor_izchil_chk CHECK (
        tasdiq_ishonch IS NULL
        OR (tasdiq_ishonch IN ('erp_sessiya', 'aktor_elon')
            AND tasdiq_actor_id IS NOT NULL)
        OR (tasdiq_ishonch IN ('servis', 'kuzatuvdan_oldin',
                               'kompaniya_sessiyasi')
            AND tasdiq_actor_id IS NULL)
    );

-- IJARACHI IZOLYATSIYASI: A kompaniya B ning aktorini ko'rsata
-- olmasin. Kompozit FK — `actor_ijarachi_kaliti` shuning uchun bor.
ALTER TABLE catalog_product_code
    DROP CONSTRAINT IF EXISTS catalog_product_code_tasdiq_actor_fk;
ALTER TABLE catalog_product_code
    ADD CONSTRAINT catalog_product_code_tasdiq_actor_fk
        FOREIGN KEY (company_id, tasdiq_actor_id)
        REFERENCES actor (company_id, id) ON DELETE RESTRICT;

-- ---------------------------------------------------------------------------
-- 4. YO'NALTIRISH — inson qarorida VAQT majburiy
-- ---------------------------------------------------------------------------
-- O'LCHANDI: bu shart avval YO'Q edi. Hozirgi 31 qatorning
-- hammasida vaqt bor, ya'ni cheklov ma'lumotni buzmaydi — u
-- KELAJAKDAGI vaqtsiz qarorni to'xtatadi.
ALTER TABLE tender_routing
    DROP CONSTRAINT IF EXISTS tender_routing_inson_vaqt_chk;
ALTER TABLE tender_routing
    ADD CONSTRAINT tender_routing_inson_vaqt_chk CHECK (
        inson_qaror IS NULL OR qaror_vaqti IS NOT NULL
    );

-- ---------------------------------------------------------------------------
-- 5. TALAB KO'RIGI — "ISHONCHIM KOMIL EMAS" holati
-- ---------------------------------------------------------------------------
-- Ko'ruvchida faqat approve/reject/correct bor edi. Ishonchi komil
-- bo'lmagan ko'ruvchi MAJBURAN uchtasidan birini tanlardi va bu
-- o'lchovni BUZARDI: shubha "tasdiq" bo'lib yozilardi.
ALTER TABLE tender_requirement
    DROP CONSTRAINT IF EXISTS tender_requirement_review_chk;
ALTER TABLE tender_requirement
    ADD CONSTRAINT tender_requirement_review_chk CHECK (
        review_status IN ('extracted', 'pending_review', 'approved',
                          'rejected', 'corrected', 'uncertain')
    );

ALTER TABLE tender_requirement
    DROP CONSTRAINT IF EXISTS tender_requirement_amal_chk;
ALTER TABLE tender_requirement
    ADD CONSTRAINT tender_requirement_amal_chk CHECK (
        review_action IS NULL
        OR (review_action = 'approve'   AND review_status = 'approved')
        OR (review_action = 'reject'    AND review_status = 'rejected')
        OR (review_action = 'correct'   AND review_status = 'corrected')
        OR (review_action = 'uncertain' AND review_status = 'uncertain')
    );

-- `uncertain` HAM inson qarori: aktor va vaqt shu darajada majburiy.
ALTER TABLE tender_requirement
    DROP CONSTRAINT IF EXISTS tender_requirement_inson_qarori_chk;
ALTER TABLE tender_requirement
    ADD CONSTRAINT tender_requirement_inson_qarori_chk CHECK (
        review_status NOT IN ('approved', 'rejected', 'corrected',
                              'uncertain')
        OR (reviewed_by IS NOT NULL AND reviewed_by <> 0
            AND reviewed_at IS NOT NULL AND review_action IS NOT NULL)
    );

ALTER TABLE tender_requirement
    DROP CONSTRAINT IF EXISTS tender_requirement_inson_ishonch_chk;
ALTER TABLE tender_requirement
    ADD CONSTRAINT tender_requirement_inson_ishonch_chk CHECK (
        review_status NOT IN ('approved', 'rejected', 'corrected',
                              'uncertain')
        OR reviewed_ishonch IS NOT NULL
    );

-- ---------------------------------------------------------------------------
-- 6. HALOL HISOBLAGICH
-- ---------------------------------------------------------------------------
-- Uch daraja ATAYLAB ajratilgan. "Inson qarori" bitta ustun bo'lsa
-- yana o'sha xato takrorlanardi.
--
--   aktorli    — erp_sessiya | aktor_elon: KIM ekani ma'lum
--   anonim     — kompaniya_sessiyasi: odam, lekin shaxsan noma'lum
--   mashina    — servis | kuzatuvdan_oldin: INSON EMAS
--
-- Sifat darvozasi FAQAT `aktorli` ni sanaydi.
DROP VIEW IF EXISTS v_inson_dalil CASCADE;
CREATE VIEW v_inson_dalil AS
SELECT 'kod_tasdigi'::text AS qatlam,
       company_id,
       count(*) AS jami,
       count(*) FILTER (
           WHERE tasdiq_ishonch IN ('erp_sessiya', 'aktor_elon')
       ) AS aktorli,
       count(*) FILTER (
           WHERE tasdiq_ishonch = 'kompaniya_sessiyasi'
       ) AS anonim,
       count(*) FILTER (
           WHERE tasdiq_ishonch IN ('servis', 'kuzatuvdan_oldin')
       ) AS mashina,
       count(*) FILTER (
           WHERE tasdiqlandi IS NULL AND rad_etildi IS NULL
       ) AS navbatda
  FROM catalog_product_code
 GROUP BY company_id

UNION ALL

SELECT 'talab_korigi'::text,
       company_id,
       count(*),
       count(*) FILTER (
           WHERE review_status IN ('approved', 'rejected', 'corrected',
                                   'uncertain')
             AND reviewed_ishonch IN ('erp_sessiya', 'aktor_elon')),
       count(*) FILTER (
           WHERE review_status IN ('approved', 'rejected', 'corrected',
                                   'uncertain')
             AND reviewed_ishonch = 'kompaniya_sessiyasi'),
       count(*) FILTER (
           WHERE review_status IN ('approved', 'rejected', 'corrected',
                                   'uncertain')
             AND reviewed_ishonch IN ('servis', 'kuzatuvdan_oldin')),
       count(*) FILTER (WHERE review_status = 'pending_review')
  FROM tender_requirement
 GROUP BY company_id

UNION ALL

SELECT 'yonaltirish'::text,
       company_id,
       count(*),
       count(*) FILTER (
           WHERE inson_qaror IS NOT NULL
             AND qaror_ishonch IN ('erp_sessiya', 'aktor_elon')),
       count(*) FILTER (
           WHERE inson_qaror IS NOT NULL
             AND qaror_ishonch = 'kompaniya_sessiyasi'),
       count(*) FILTER (
           WHERE inson_qaror IS NOT NULL
             AND qaror_ishonch IN ('servis', 'kuzatuvdan_oldin')),
       count(*) FILTER (WHERE inson_qaror IS NULL)
  FROM tender_routing
 GROUP BY company_id;

COMMENT ON VIEW v_inson_dalil IS
    'Inson qarorini DALIL darajasi bo''yicha ajratadi. `aktorli` — '
    'kim ekani ma''lum. Sifat darvozasi faqat shuni sanaydi.';

-- ---------------------------------------------------------------------------
-- 7. 0068 DAGI HISOBLAGICH TUZATILADI
-- ---------------------------------------------------------------------------
-- Eski `v_inson_halqasi` mashina qatorlarini inson deb sanardi.
-- U SAQLANADI (eski so'rovlar yiqilmasin), lekin endi DALIL
-- darajasidan hisoblanadi.
DROP VIEW IF EXISTS v_inson_halqasi CASCADE;
CREATE VIEW v_inson_halqasi AS
SELECT qatlam,
       company_id,
       jami,
       aktorli AS inson_qarori,
       navbatda,
       round(100.0 * aktorli / NULLIF(jami, 0), 1) AS foiz,
       anonim,
       mashina
  FROM v_inson_dalil;

COMMENT ON VIEW v_inson_halqasi IS
    '`inson_qarori` endi FAQAT aktorli qarorni sanaydi. 2026-09-02 '
    'gacha u mashina qatorlarini ham sanardi va 73.4% bergan edi.';

-- ---------------------------------------------------------------------------
-- 8. SIFAT DARVOZASI
-- ---------------------------------------------------------------------------
-- Uch holat ATAYLAB ajratilgan va ular BIR-BIRINI ALMASHTIRMAYDI:
--
--   AMALGA_OSHIRILDI  kod bor
--   SINALDI           avtomatik sinov o'tadi
--   INSON_TASDIQLADI  yetarli sondagi AKTORLI inson qarori bor
--
-- Eng past bosqich g'olib: sinovsiz kod "sinaldi" bo'la olmaydi.
--
-- ENG KAM NAMUNA — SIYOSAT, STATISTIKA EMAS. Bu raqamlar ishonch
-- oralig'idan chiqarilmagan; ular "shu qatlamni baholash uchun
-- eng kami" degan muhandislik qarori. Namuna kichik bo'lsa
-- ko'rinish `YETARLI_EMAS` deydi va FOIZ HAM CHIQARMAYDI —
-- 3 ta qarordan 67% chiqarish yolg'on aniqlik bo'lardi.
DROP VIEW IF EXISTS v_sifat_darvoza CASCADE;
CREATE VIEW v_sifat_darvoza AS
WITH chegara(qatlam, eng_kam) AS (
    VALUES ('kod_tasdigi'::text,  40),
           ('talab_korigi'::text, 200),
           ('yonaltirish'::text,  50)
)
SELECT d.qatlam,
       d.company_id,
       c.eng_kam,
       d.aktorli,
       GREATEST(0, c.eng_kam - d.aktorli::int) AS qolgan,
       d.anonim,
       d.mashina,
       d.navbatda,
       CASE WHEN d.aktorli >= c.eng_kam THEN 'INSON_TASDIQLADI'
            WHEN d.aktorli > 0          THEN 'YETARLI_EMAS'
            ELSE 'TASDIQLANMAGAN'
       END AS holat,
       -- Foiz FAQAT chegaradan o'tgach hisoblanadi.
       CASE WHEN d.aktorli >= c.eng_kam
            THEN round(100.0 * d.aktorli / NULLIF(d.jami, 0), 1)
       END AS ulush_foiz
  FROM v_inson_dalil d
  JOIN chegara c ON c.qatlam = d.qatlam;

COMMENT ON VIEW v_sifat_darvoza IS
    'Chegaradan o''tmagan qatlam uchun FOIZ QAYTARILMAYDI — kichik '
    'namunadan aniqlik uydirilmasin.';

COMMIT;
