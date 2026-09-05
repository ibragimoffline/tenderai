-- =============================================================================
-- Sxema patch — `dim_area` UCHUN VILOYAT URUG'I (seed)
-- Ishga tushirish (idempotent, bir necha marta ishlatsa ham xavfsiz):
--   psql "$XT_DB_DSN_OWNER" -f schema_patch_dim_area_seed.sql
-- Talab: xt_xarid_schema.sql (dim_area).
--
-- MUAMMO. `tender.area_leaf_id` -> `dim_area(area_id)` ga FOREIGN KEY.
-- `dim_area` ni faqat `etl_dims.py` to'ldiradi, u esa ma'lumotni
-- xt-xarid RPC dan oladi. Manba o'chiq bo'lsa jadval BO'SH qoladi va
-- shunda UZEX ma'lumoti ham yozilmaydi -- garchi uzex butunlay
-- BOSHQA manba bo'lsa ham:
--
--     ! #509465 DB xato: insert or update on table "tender" violates
--       foreign key constraint "tender_area_leaf_id_fkey"
--     Metrika: ko'rildi 655, yozildi 0, yiqildi 655
--
-- O'LCHANDI 2026-09-04: xt-xarid `/rpc` bir necha soat `521
-- "Технические работы"` qaytardi va shu vaqt ichida IKKALA manba ham
-- to'xtab qoldi. Bitta manbaning uzilishi ikkinchisini ham
-- o'ldirmasligi kerak.
--
-- YECHIM. `etl_uzex.py` ning `REGION_MAP` i uzex hududlarini BIZNING
-- kanonik kodlarga solishtiradi va o'sha 14 ta kod -- `region_for()`
-- qaytara oladigan YAGONA qiymatlar to'plami (u `REGION_ALIASES`
-- kalitlaridan boshqa hech narsa qaytarmaydi). Ya'ni uzex uchun
-- aynan shu 14 qator YETARLI.
--
-- MA'LUMOT O'YLAB TOPILMADI: kodlar ham, nomlar ham `etl_uzex.py`
-- dagi `REGION_MAP` dan olingan. `33` ildizi sxema izohida
-- ("'33' (root)") va `schema_patch_multiplatform.sql` da yozilgan.
-- Ildizning NOMI qo'yilmadi -- uni reestr beradi.
--
-- HAQIQIY REESTRNI BUZMAYDI: `ON CONFLICT DO NOTHING`. `etl_dims.py`
-- esa `ON CONFLICT (area_id) DO UPDATE` ishlatadi, ya'ni manba
-- tiklangach BU QATORLAR ustiga to'liq ma'lumot yoziladi (parent_id,
-- name_ru, level, has_children, full_path). Seed -- vaqtinchalik
-- suyanchiq, doimiy haqiqat emas.
--
-- CHEKLOV: `parent_id` va ierarxiya faqat viloyat darajasigacha.
-- Tuman bo'yicha filtr reestr yuklangunga qadar ishlamaydi.
-- =============================================================================

INSERT INTO dim_area (area_id, parent_id, name_uz, level, full_path) VALUES
    ('33', NULL, NULL, 0, '33')
ON CONFLICT (area_id) DO NOTHING;

INSERT INTO dim_area (area_id, parent_id, name_uz, level, full_path) VALUES
    ('33.34', '33', 'Andijon viloyati', 1, '33.34'),
    ('33.274', '33', 'Buxoro viloyati', 1, '33.274'),
    ('33.519', '33', 'Jizzax viloyati', 1, '33.519'),
    ('33.711', '33', 'Qashqadaryo viloyati', 1, '33.711'),
    ('33.1040', '33', 'Navoiy viloyati', 1, '33.1040'),
    ('33.1182', '33', 'Namangan viloyati', 1, '33.1182'),
    ('33.1445', '33', 'Samarqand viloyati', 1, '33.1445'),
    ('33.1724', '33', 'Surxondaryo viloyati', 1, '33.1724'),
    ('33.2009', '33', 'Sirdaryo viloyati', 1, '33.2009'),
    ('33.2137', '33', 'Toshkent shahri', 1, '33.2137'),
    ('33.2152', '33', 'Toshkent viloyati', 1, '33.2152'),
    ('33.2466', '33', 'Farg‘ona viloyati', 1, '33.2466'),
    ('33.2890', '33', 'Xorazm viloyati', 1, '33.2890'),
    ('33.3081', '33', 'Qoraqalpog‘iston Respublikasi', 1, '33.3081')
ON CONFLICT (area_id) DO NOTHING;

-- --- TEKSHIRUV: natija KO'RINSIN --------------------------------------------
SELECT 'dim_area viloyatlari' AS tekshiruv,
       count(*) FILTER (WHERE level = 1) AS qiymat,
       14 AS kutilgan
FROM dim_area;
