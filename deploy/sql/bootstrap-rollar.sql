-- =====================================================================
-- KLASTER ROLLARI — BOOTSTRAP (SUPERUSER, BIR MARTA)
-- =====================================================================
-- Yurgizish:
--     sudo -u postgres psql -f deploy/sql/bootstrap-rollar.sql
--
-- NEGA MIGRATSIYADA EMAS
-- ----------------------
-- Rol atributlari (SUPERUSER, CREATEDB, CREATEROLE, BYPASSRLS,
-- REPLICATION, LOGIN) KLASTER darajasidagi ma'muriyat: ular bitta
-- bazaga emas, butun serverga tegishli. Sxema migratsiyasi esa BITTA
-- bazani o'zgartiradi.
--
-- Bu chegara nazariy emas. `schema_patch_huquq.sql` (0057_huquq)
-- ilgari `ALTER ROLE tai_app NOSUPERUSER …` yuborardi va PostgreSQL
-- SUPERUSER atributini o'zgartirish uchun -- HATTO OLIB TASHLASH uchun
-- ham -- superuser talab qiladi. O'lchangan (2026-09-09): bo'sh
-- bazadan qayta qurish aynan shu qatorda to'xtadi, garchi `tai_app`
-- allaqachon `NOSUPERUSER` bo'lsa ham. Ya'ni "zararsiz idempotent
-- himoya" butun falokatdan tiklash yo'lini superuser'ga bog'lab
-- qo'ygan edi.
--
-- Endi mas'uliyat ajratilgan:
--     BOOTSTRAP (shu fayl)  -- rollarni yaratadi, atributlarni beradi
--     MIGRATSIYA            -- holatni tekshiradi, baza ichidagi
--                              huquqlarni beradi, siljishda TO'XTAYDI
--
-- IDEMPOTENT: bir necha marta yurgizsa bo'ladi.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1) tai_app — ILOVA GURUH ROLI
-- ---------------------------------------------------------------------
-- NOLOGIN: bu guruh roli, u bilan to'g'ridan-to'g'ri ULANILMAYDI.
-- INHERIT: a'zo rol (`tai_service`) huquqlarni oladi.
--
-- Hech qanday klaster imtiyozi YO'Q va bo'lmaydi ham. Migratsiya buni
-- har yurishda tekshiradi va buzilgan bo'lsa to'xtaydi.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tai_app') THEN
        CREATE ROLE tai_app NOLOGIN INHERIT;
        RAISE NOTICE 'tai_app yaratildi.';
    ELSE
        RAISE NOTICE 'tai_app allaqachon bor.';
    END IF;
END $$;

-- ATRIBUTLAR SHU YERDA O'RNATILADI — migratsiyada emas.
-- Bu fayl superuser bilan yuriladi, ya'ni buyruq bu yerda O'TADI.
ALTER ROLE tai_app
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION NOLOGIN;

-- ---------------------------------------------------------------------
-- 2) tai_service — ILOVA ULANISH ROLI
-- ---------------------------------------------------------------------
-- PAROL SHU FAYLDA YO'Q va bo'lmasligi kerak: fayl repozitoriyada
-- turadi. Rolni parol bilan operator yaratadi:
--
--     CREATE ROLE tai_service LOGIN PASSWORD '<kuchli tasodifiy>';
--     GRANT tai_app TO tai_service;
--
-- Quyidagi blok faqat MAVJUD rolning atributlarini qattiqlashtiradi.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tai_service') THEN
        ALTER ROLE tai_service
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;
        RAISE NOTICE 'tai_service atributlari qattiqlashtirildi.';
    ELSE
        RAISE NOTICE 'tai_service hali yo''q — docs/deploy.md §4 ga qarang.';
    END IF;
END $$;

-- ---------------------------------------------------------------------
-- 3) HOLAT — nima bo'lganini KO'RSATADI
-- ---------------------------------------------------------------------
-- Sir chiqmaydi: faqat rol nomi va klaster bayroqlari.
SELECT rolname,
       rolsuper       AS super,
       rolcreatedb    AS createdb,
       rolcreaterole  AS createrole,
       rolbypassrls   AS bypassrls,
       rolreplication AS replication,
       rolcanlogin    AS login
  FROM pg_roles
 WHERE rolname IN ('tai_app', 'tai_service', 'tai_owner', 'tai_test_admin')
 ORDER BY rolname;
