-- =====================================================================
-- `v_chat_tiklash` — MEDIANA va ENG KAM NAMUNA
-- =====================================================================
--
-- Ko'rinish 0081 da qo'shildi va ikkita nuqson bilan chiqdi. Ikkalasi
-- ham SHU LOYIHADA allaqachon o'rganilgan saboqning qaytishi —
-- shuning uchun tuzatish alohida migratsiya bilan yoziladi, jimgina
-- almashtirilmaydi.
--
-- 1) O'RTACHA -> MEDIANA
--
--    `avg(tiklash_rad_at - tiklandi_at)` bitta uzun holatdan buziladi:
--    foydalanuvchi panelni ochib qoldirib ketadi va 40 daqiqadan
--    keyin "Yangi suhbat" bosadi. Bitta shunday qator o'nta tez
--    rad etishning o'rtachasini o'nlab barobar suradi.
--
--    Vaqt o'lchovida bu loyiha allaqachon MEDIANAni tanlagan
--    (`requirements/speed`, `sekund_talabga`). Bu yerda o'rtacha
--    yozilgani izchillikning buzilishi edi.
--
-- 2) ENG KAM NAMUNA — `TIKLASH_MIN = 10`
--
--    Maxraj nol bo'lganda foiz NULL bo'lardi (0081 da to'g'ri
--    qilingan), lekin MAXRAJ 3 bo'lganda 2 rad etish `66.7%`
--    beradi va u "chegara noto'g'ri" deb o'qiladi.
--
--    Bu `routing.MOSLIK_MIN = 10` bilan AYNI qoida: kam namunadan
--    foiz chiqarish — "bitta qarordan 100%" xatosining o'zi.
--    Raqam ATAYLAB bir xil: ikkalasi ham "foiz berish uchun eng
--    kam kuzatuv" degan bitta savolga javob beradi.
--
--    Maxraj ALOHIDA ustunda qoladi (`tiklandi`), ya'ni "hali
--    o'lchanmagan" holat KO'RINADI — foiz NULL bo'lgani bilan
--    ma'lumot yashirilmaydi.
--
-- Qo'llash:
--   .venv\Scripts\python.exe migratsiya.py --qolla
-- =====================================================================

BEGIN;

-- USTUN NOMI O'ZGARADI (`ortacha_sek` -> `mediana_sek`) va yangisi
-- qo'shiladi, shuning uchun `CREATE OR REPLACE` YETMAYDI: PostgreSQL
-- mavjud ko'rinishning ustun ro'yxatini o'zgartirishga ruxsat
-- bermaydi. Chiqarib tashlab qayta yaratamiz.
--
-- ===================================================================
-- QOIDA: `DROP VIEW` DAN OLDIN IKKI NARSA TEKSHIRILADI
-- ===================================================================
-- `DROP VIEW` faqat ta'rifni emas, ATROFIDAGINI ham oladi:
--
--   1. GRANT lar YO'QOLADI. Ko'rinish qayta yaratilganda huquqlar
--      tiklanmaydi -- `erp` roli `SELECT` qila olmay qoladi va bu
--      FAQAT ishlab chiqarishda, boshqa loyihada ko'rinadi
--      (`schema_patch_topshiriq.sql` dagi `GRANT SELECT ON
--      v_erp_topshiriq TO erp` -- aynan shunday qatorlar bor).
--
--   2. BOG'LIQ OBYEKTLAR. Ko'rinishga boshqa ko'rinish yoki
--      funksiya bog'langan bo'lsa `DROP` xato beradi, `CASCADE`
--      esa BOG'LANGANINI HAM O'CHIRADI -- va uni qayta yaratish
--      shu patchda yozilmagan bo'lsa, u JIMGINA yo'qoladi.
--
-- Tekshirish (`DROP` dan OLDIN, qo'lda):
--
--   -- bog'liqliklar:
--   SELECT DISTINCT dependent.relname
--     FROM pg_depend d
--     JOIN pg_rewrite r  ON r.oid = d.objid
--     JOIN pg_class dependent ON dependent.oid = r.ev_class
--    WHERE d.refobjid = 'public.v_chat_tiklash'::regclass
--      AND dependent.relname <> 'v_chat_tiklash';
--
--   -- grantlar:
--   \dp v_chat_tiklash        -- yoki:
--   SELECT grantee, privilege_type FROM information_schema.table_privileges
--    WHERE table_name = 'v_chat_tiklash';
--
-- Bog'liqlik yoki grant BO'LSA -- ularni shu patchda QAYTA yozing.
--
-- BU OILA ALLAQACHON TISHLAGAN: bir necha navbat oldin
-- `ALTER COLUMN TYPE` ko'rinishga urilgan edi. O'sha darsning
-- davomi -- sxema obyekti hech qachon YOLG'IZ turmaydi.
--
-- SHU BAZADA GRANTLAR AVTOMATIK TIKLANADI -- LEKIN HAMMASI EMAS.
--
-- O'lchandi (2026-09-04): `pg_default_acl` da `postgres` roli uchun
-- relation turiga (`defaclobjtype = 'r'`) ikkita yozuv bor --
-- `tai_app=arwd` va `erp=arwd`. Ya'ni `postgres` yaratgan har yangi
-- ko'rinish shu ikki rolga huquqni O'ZI oladi va `DROP` + `CREATE`
-- dan keyin `tai_app` `SELECT` qila oladi (tekshirildi).
--
-- BU KAFOLAT EMAS. Standart privilegiyalar faqat STANDART huquqni
-- qaytaradi. Ko'rinishga QO'LDA berilgan qo'shimcha `GRANT` yoki
-- ataylab qo'yilgan `REVOKE` -- QAYTMAYDI va buni hech narsa
-- aytmaydi. Shuning uchun tekshiruv `DROP` dan oldin baribir
-- qilinadi, "avtomatik tiklanadi" degan xotirjamlikka
-- tayanilmaydi.
--
-- SHU YERDA: bog'liq obyekt YO'Q (birinchi so'rov bo'sh qaytdi),
-- grantlar esa standart privilegiyalardan -- qo'lda berilgani
-- yo'q. `DROP` xavfsiz.
DROP VIEW IF EXISTS v_chat_tiklash;
CREATE VIEW v_chat_tiklash AS
SELECT
    company_id,
    CASE WHEN tender_id IS NULL THEN 'global' ELSE 'tender' END AS kesim,
    count(*) FILTER (WHERE tiklandi_at IS NOT NULL)     AS tiklandi,
    count(*) FILTER (WHERE tiklash_rad_at IS NOT NULL)  AS rad_etildi,

    -- FOIZ IKKI SHART BILAN: maxraj nol EMAS va >= 10.
    --
    -- `CASE` ikkalasini ham bajaradi: maxraj 10 dan kichik bo'lsa
    -- shox umuman hisoblanmaydi va natija NULL bo'ladi. Ya'ni
    -- "o'lchanmagan" va "0%" HECH QACHON bir xil ko'rinmaydi.
    CASE WHEN count(*) FILTER (WHERE tiklandi_at IS NOT NULL) >= 10
         THEN round(100.0 * count(*) FILTER (WHERE tiklash_rad_at IS NOT NULL)
                    / count(*) FILTER (WHERE tiklandi_at IS NOT NULL), 1)
    END AS rad_foiz,

    -- Foiz NULL bo'lsa NEGA ekani AYTILADI. Aks holda operator
    -- "hisoblanmadi" ni "xato" deb o'qirdi.
    CASE WHEN count(*) FILTER (WHERE tiklandi_at IS NOT NULL) < 10
         THEN 'namuna kam: '
              || count(*) FILTER (WHERE tiklandi_at IS NOT NULL) || '/10'
    END AS foiz_yoq_sababi,

    -- MEDIANA, o'rtacha EMAS: bitta uzun holat (panel ochiq
    -- qoldirilgan) o'rtachani buzadi.
    percentile_cont(0.5) WITHIN GROUP (
        ORDER BY EXTRACT(EPOCH FROM (tiklash_rad_at - tiklandi_at))
    ) FILTER (WHERE tiklash_rad_at IS NOT NULL)::int AS mediana_sek
FROM chat_session
WHERE manba IS DISTINCT FROM 'eval'
GROUP BY company_id, 2;

COMMENT ON VIEW v_chat_tiklash IS
    'Suhbat tiklanishi qabul qilindimi. `rad_foiz` yuqori bo`lsa '
    '`DAVOM_SOAT` chegarasi o`sha kesim uchun noto`g`ri. Global va '
    'tenderli ALOHIDA. Foiz FAQAT >= 10 tiklanishda beriladi '
    '(`routing.MOSLIK_MIN` bilan ayni qoida); aks holda NULL va '
    'sababi `foiz_yoq_sababi` da. Vaqt — MEDIANA, o`rtacha emas.';

-- --- MUSBAT TASDIQ ----------------------------------------------------
DO $$
DECLARE d TEXT;
BEGIN
    d := pg_get_viewdef('public.v_chat_tiklash'::regclass, true);
    IF d LIKE '%avg(%' THEN
        RAISE EXCEPTION 'v_chat_tiklash hali o`rtachani ishlatyapti';
    END IF;
    IF d NOT LIKE '%percentile_cont%' THEN
        RAISE EXCEPTION 'v_chat_tiklash da mediana yo`q';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'v_chat_tiklash'
                      AND column_name = 'foiz_yoq_sababi') THEN
        RAISE EXCEPTION 'foiz_yoq_sababi ustuni yo`q';
    END IF;
END $$;

COMMIT;

-- =====================================================================
-- ROLLBACK: 0081 dagi ta'rifni qayta qo'llang
--   (`schema_patch_chat_tiklash.sql` dagi CREATE OR REPLACE VIEW).
-- =====================================================================
