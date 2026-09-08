-- =====================================================================
-- ENG KAM HUQUQ — ilova SUPERUSER sifatida ishlamasin
-- =====================================================================
--
-- O'LCHANGAN MUAMMO (2026-08-31, `xtxarid` bazasi so'ralgan):
--
--     current_user = postgres
--     rolsuper     = true      rolcreatedb = true
--     rolcreaterole= true      rolbypassrls = true
--
--   Ya'ni ilova bazaga SUPERUSER sifatida ulanadi. Buning uchta
--   aniq oqibati bor va ular nazariy emas:
--
--   1. SQL INYEKSIYASI TO'LIQ EGALLASH bo'lardi. Hozir SQL
--      parametrlangan (tekshirildi: `ORDER BY` oq ro'yxat bilan,
--      qolgan interpolatsiyalar KONSTANTA ustun ro'yxatlari), lekin
--      bitta kelajakdagi xato butun klasterni ochib berardi.
--
--   2. AUDIT JURNALI QULFI ILOVANING O'ZI TOMONIDAN yechilardi.
--      `audit_jurnal` append-only bo'lishi trigger bilan
--      ta'minlangan; superuser esa `ALTER TABLE ... DISABLE TRIGGER`
--      yoki `DROP TRIGGER` qila oladi. Ya'ni "audit qayta yozilmaydi"
--      degan kafolat ILOVA ISHONCHIGA tayanardi.
--
--   3. ERP CHEGARASI FAQAT SINOV BILAN himoyalangan edi.
--      `_tests/auth_test.py` har yurishda `erp.app_user` suratini
--      oladi va tender-ai yozgan bo'lsa yiqiladi. Bu YAXSHI, lekin u
--      KEYIN aytadi. Huquq esa OLDIN to'sadi.
--
-- BU PATCH NIMA QILADI
--   `tai_app` — LOGIN SIZ rol (guruh). Unga ilovaga kerakli minimal
--   huquqlar beriladi va `erp.*` dan FAQAT shartnoma-view lari.
--
-- NEGA LOGIN SIZ VA PAROLSIZ: parol repozitoriyga tushmasligi kerak.
--   Operator o'zi LOGIN roli yaratadi va unga `tai_app` ni beradi:
--
--       CREATE ROLE tai_service LOGIN PASSWORD '<kuchli parol>';
--       GRANT tai_app TO tai_service;
--       -- .env:  XT_DB_DSN=... user=tai_service password=...
--
--   Batafsil: `docs/xavfsizlik.md` §4.
--
-- MIGRATSIYALAR BOSHQA ROL BILAN. `tai_app` da DDL huquqi YO'Q va bu
--   ATAYLAB: ilova sxemani o'zgartira olmasligi kerak.
--   `migratsiya.py` egasi (`postgres` yoki alohida `tai_owner`) bilan
--   yuriladi.
--
-- Idempotent: bir necha marta yurgizsa bo'ladi.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1) Rol
-- ---------------------------------------------------------------------
-- BU BO'LIM ROLNI YARATMAYDI VA O'ZGARTIRMAYDI — TEKSHIRADI.
--
-- ILGARI shunday edi:
--     CREATE ROLE tai_app NOLOGIN INHERIT;          -- CREATEROLE kerak
--     ALTER ROLE  tai_app NOSUPERUSER NOCREATEDB …; -- SUPERUSER kerak
--
-- O'LCHANGAN (2026-09-09, darvoza): bo'sh bazadan qayta qurish
-- 57-migratsiyada to'xtardi:
--
--     permission denied to alter role
--     DETAIL: Only roles with the SUPERUSER attribute may change
--             the SUPERUSER attribute.
--
-- MUHIM TAFSILOT: `tai_app` O'SHA PAYTDA ALLAQACHON `NOSUPERUSER` edi.
-- Ya'ni PostgreSQL imtiyozni buyruq BO'SH ISH bo'lganda ham talab
-- qiladi. Demak "zararsiz idempotent himoya" aslida butun tiklash
-- yo'lini superuser'ga bog'lab qo'ygan edi.
--
-- MAS'ULIYAT AJRATILDI:
--   BOOTSTRAP (superuser, bir marta)  -- rolni YARATADI va klaster
--                                        atributlarini o'rnatadi;
--                                        `deploy/sql/bootstrap-rollar.sql`
--   MIGRATSIYA (egasi roli)           -- rol holatini TEKSHIRADI va
--                                        baza ichidagi huquqlarni beradi.
--
-- SILJISH JIMGINA O'TMAYDI. Rolda taqiqlangan klaster atributi bo'lsa
-- migratsiya TO'XTAYDI. U buni O'ZI TUZATMAYDI: tuzatish superuser
-- aralashuvini talab qiladi va bunday hodisa ko'rinishi kerak, jimgina
-- "tuzatilib" o'tib ketmasligi kerak.
DO $$
DECLARE
    r      record;
    yomon  text[] := ARRAY[]::text[];
BEGIN
    SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls,
           rolreplication, rolcanlogin
      INTO r
      FROM pg_roles WHERE rolname = 'tai_app';

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'ROL YO''Q: tai_app. Bu migratsiya rol YARATMAYDI.'
            USING HINT = 'Avval bootstrap: deploy/sql/bootstrap-rollar.sql '
                         '(superuser, bir marta) — docs/deploy.md §4.';
    END IF;

    IF r.rolsuper       THEN yomon := yomon || 'SUPERUSER';   END IF;
    IF r.rolcreatedb    THEN yomon := yomon || 'CREATEDB';    END IF;
    IF r.rolcreaterole  THEN yomon := yomon || 'CREATEROLE';  END IF;
    IF r.rolbypassrls   THEN yomon := yomon || 'BYPASSRLS';   END IF;
    IF r.rolreplication THEN yomon := yomon || 'REPLICATION'; END IF;
    IF r.rolcanlogin    THEN yomon := yomon || 'LOGIN';       END IF;

    IF array_length(yomon, 1) IS NOT NULL THEN
        RAISE EXCEPTION
            'SECURITY_ROLE_DRIFT: tai_app taqiqlangan klaster atribut(lar)iga ega: %',
            array_to_string(yomon, ', ')
            USING HINT = 'Tuzatish SUPERUSER aralashuvini talab qiladi: '
                         'ALTER ROLE tai_app NOSUPERUSER NOCREATEDB '
                         'NOCREATEROLE NOBYPASSRLS NOREPLICATION NOLOGIN; '
                         'Sabab tekshirilsin — rol qo''lda ko''tarilgan.';
    END IF;

    RAISE NOTICE 'tai_app: klaster atributlari toza (tekshirildi).';
END $$;

-- ---------------------------------------------------------------------
-- 2) public — ilova ishlaydigan joy
-- ---------------------------------------------------------------------
GRANT USAGE ON SCHEMA public TO tai_app;

-- Ilova o'qiydi va yozadi, LEKIN sxemani o'zgartira olmaydi:
-- `CREATE` huquqi BERILMAYDI.
REVOKE CREATE ON SCHEMA public FROM tai_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tai_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tai_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO tai_app;

-- Kelajakdagi jadvallar ham. Busiz keyingi migratsiya yangi jadval
-- qo'shsa ilova unga tegishli huquqsiz qolardi va buni faqat ishlab
-- chiqarishdagi xato ko'rsatardi.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tai_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO tai_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO tai_app;

-- ---------------------------------------------------------------------
-- 3) AUDIT JURNALI — huquq darajasida ham qulflanadi
-- ---------------------------------------------------------------------
-- Trigger allaqachon `UPDATE`/`DELETE` ni to'sadi. Bu IKKINCHI qatlam:
-- trigger o'chirilsa ham (buning uchun EGALIK kerak, `tai_app` da u
-- yo'q) huquq qolmaydi.
--
-- `SELECT` va `INSERT` QOLADI: audit yozilishi va o'qilishi kerak.
DO $$
BEGIN
    IF to_regclass('public.audit_jurnal') IS NOT NULL THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON public.audit_jurnal FROM tai_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT ON TABLES TO tai_app;
    END IF;
END $$;

-- ---------------------------------------------------------------------
-- 4) ERP CHEGARASI — endi HUQUQ bilan
-- ---------------------------------------------------------------------
-- Shartnoma: tender-ai `erp.*` ning FAQAT view laridan o'qiydi,
-- HECH QACHON yozmaydi. Shu paytgacha buni faqat sinov tekshirardi.
--
-- `erp` sxemasi bo'lmasa (ERP o'rnatilmagan) bu blok JIMGINA
-- o'tkazib yuboriladi — bu XATO EMAS, `erp_status.ready()` bilan bir
-- xil naqsh.
DO $$
DECLARE v TEXT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.schemata
                   WHERE schema_name = 'erp') THEN
        RAISE NOTICE 'erp sxemasi yo''q — chegara huquqlari o''tkazib yuborildi.';
        RETURN;
    END IF;

    GRANT USAGE ON SCHEMA erp TO tai_app;
    -- HECH NARSA berilmaydi, keyin FAQAT shartnoma-view lari beriladi.
    REVOKE ALL ON ALL TABLES IN SCHEMA erp FROM tai_app;
    REVOKE ALL ON ALL SEQUENCES IN SCHEMA erp FROM tai_app;
    REVOKE ALL ON ALL FUNCTIONS IN SCHEMA erp FROM tai_app;
    REVOKE CREATE ON SCHEMA erp FROM tai_app;

    FOREACH v IN ARRAY ARRAY['v_tender_status', 'v_stock_balance', 'v_tai_actor']
    LOOP
        IF to_regclass('erp.' || v) IS NOT NULL THEN
            EXECUTE format('GRANT SELECT ON erp.%I TO tai_app', v);
            RAISE NOTICE 'erp.% -> SELECT berildi.', v;
        ELSE
            RAISE NOTICE 'erp.% hali yo''q — o''tkazib yuborildi.', v;
        END IF;
    END LOOP;

    -- Kelajakdagi ERP jadvallariga AVTOMATIK huquq BERILMAYDI:
    -- default privilege ATAYLAB qo'yilmaydi. Yangi view kerak bo'lsa
    -- u shu ro'yxatga ONGLI ravishda qo'shiladi.
END $$;

-- ---------------------------------------------------------------------
-- 5) Nazorat ko'rinishi
-- ---------------------------------------------------------------------
DROP VIEW IF EXISTS v_huquq_tekshiruv;
CREATE VIEW v_huquq_tekshiruv AS
SELECT 'superuser'::TEXT             AS nima,
       (SELECT rolsuper FROM pg_roles WHERE rolname = 'tai_app')  AS qiymat,
       false                          AS kutilgan
UNION ALL
SELECT 'bypassrls',
       (SELECT rolbypassrls FROM pg_roles WHERE rolname = 'tai_app'), false
UNION ALL
SELECT 'public.CREATE',
       has_schema_privilege('tai_app', 'public', 'CREATE'), false
UNION ALL
SELECT 'audit_jurnal UPDATE',
       CASE WHEN to_regclass('public.audit_jurnal') IS NULL THEN NULL
            ELSE has_table_privilege('tai_app', 'public.audit_jurnal', 'UPDATE') END,
       false
UNION ALL
SELECT 'audit_jurnal DELETE',
       CASE WHEN to_regclass('public.audit_jurnal') IS NULL THEN NULL
            ELSE has_table_privilege('tai_app', 'public.audit_jurnal', 'DELETE') END,
       false
UNION ALL
SELECT 'audit_jurnal INSERT',
       CASE WHEN to_regclass('public.audit_jurnal') IS NULL THEN NULL
            ELSE has_table_privilege('tai_app', 'public.audit_jurnal', 'INSERT') END,
       true
UNION ALL
SELECT 'erp.app_user SELECT',
       CASE WHEN to_regclass('erp.app_user') IS NULL THEN NULL
            ELSE has_table_privilege('tai_app', 'erp.app_user', 'SELECT') END,
       false
UNION ALL
SELECT 'erp.v_tender_status SELECT',
       CASE WHEN to_regclass('erp.v_tender_status') IS NULL THEN NULL
            ELSE has_table_privilege('tai_app', 'erp.v_tender_status', 'SELECT') END,
       true
UNION ALL
SELECT 'company_account SELECT',
       has_table_privilege('tai_app', 'public.company_account', 'SELECT'), true;

COMMENT ON VIEW v_huquq_tekshiruv IS
    '`tai_app` roli huquqlari KUTILGAN qiymat bilan yonma-yon. '
    '`qiymat <> kutilgan` bo''lgan qator — muammo. NULL = obyekt yo''q.';

COMMIT;
