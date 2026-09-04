-- =============================================================================
-- Sxema patch — HUQUQ TUZATISHI: `tender_category` ga TRUNCATE
-- Ishga tushirish (idempotent, bir necha marta ishlatsa ham xavfsiz):
--   psql "$XT_DB_DSN_OWNER" -f schema_patch_huquq_2.sql
-- Talab: schema_patch_huquq.sql qo'llangan bo'lishi kerak.
--
-- MUAMMO. `etl_categorize.py` 116-qatorida:
--
--     cur.execute("TRUNCATE tender_category")
--
-- `schema_patch_huquq.sql` esa `tai_app` ga faqat quyidagilarni beradi:
--
--     GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES ...
--
-- PostgreSQL da TRUNCATE — ALOHIDA huquq va u DELETE ga kirmaydi.
-- Natijada ETL ning kategoriyalash qadami HAR YURISHDA yiqiladi:
--
--     psycopg2.errors.InsufficientPrivilege:
--         permission denied for table tender_category
--
-- O'LCHANDI (2026-09-04, bo'sh serverga birinchi o'rnatish): ETL ning
-- boshqa qadamlari o'tdi, kategoriyalash esa har soatda shu xato bilan
-- to'xtadi va butun yurishga `chiqish kodi 1` berdi.
--
-- NEGA AYNAN BITTA JADVAL, `ON ALL TABLES` EMAS. Butun sxemaga
-- TRUNCATE berish ilovaning zarar doirasini kengaytirardi va
-- `schema_patch_huquq.sql` ning e'lon qilgan tamoyiliga ziddir:
-- "Ilova o'qiydi va yozadi, LEKIN sxemani o'zgartira olmaydi."
-- Kod bazasida TRUNCATE BITTA joyda va BITTA jadvalga qo'llanadi —
-- huquq ham aynan shuncha bo'lsin.
--
-- NEGA KOD O'ZGARTIRILMADI (`DELETE FROM` ga). Bu ham ishlardi, lekin
-- `tender_category` HOSILAVIY jadval: u har yurishda noldan quriladi.
-- TRUNCATE aynan shu naqsh uchun mo'ljallangan va u `DELETE` dan
-- farqli o'laroq o'lik qatorlar qoldirmaydi.
--
-- NEGA YANGI FAYL, `huquq.sql` ning O'ZI EMAS. `migratsiya.py` har
-- faylning SHA-256 ini saqlaydi va qo'llangandan keyin tahrirlangan
-- faylni ko'rsa TO'XTAYDI. O'zgarish har doim yangi patch bo'lib
-- keladi.
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tai_app') THEN
        RAISE EXCEPTION '`tai_app` roli yo''q — avval schema_patch_huquq.sql';
    END IF;

    IF to_regclass('public.tender_category') IS NULL THEN
        RAISE EXCEPTION '`tender_category` jadvali yo''q — avval schema_patch_categories.sql';
    END IF;
END $$;

GRANT TRUNCATE ON public.tender_category TO tai_app;

COMMENT ON TABLE public.tender_category IS
    'Tender <-> kategoriya bog''lanishi. HOSILAVIY: `etl_categorize.py` uni '
    'har yurishda TRUNCATE qilib qayta quradi — `tai_app` da shu jadvalga '
    '(va faqat shunga) TRUNCATE huquqi bor.';

-- --- TEKSHIRUV: natija KO'RINSIN --------------------------------------------
SELECT 'tender_category TRUNCATE (tai_app)' AS tekshiruv,
       has_table_privilege('tai_app', 'public.tender_category', 'TRUNCATE') AS qiymat,
       true AS kutilgan;
