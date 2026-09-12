-- =============================================================================
-- KO'RIK NAVBATI TAHLILDAN HAM OZIQLANADI
--
--   psql "dbname=xtxarid user=postgres host=localhost" -f schema_patch_kod_navbat.sql
--
-- MUAMMO
-- ------
-- `--tahlil` FAQAT `catalog_kod_tahlil` ga yozadi. Ko'rik yozuvini esa
-- `classify_product()` yaratadi va uni `--qolla` chaqiradi. Ya'ni
-- soatlik ETL ga faqat `--tahlil` ulansa, ko'rik talab qiladigan yangi
-- mahsulotlar HECH QAYERGA tushmaydi.
--
-- `--qolla` ni cron ga ulash BU MUAMMONI YECHMAYDI va boshqasini
-- keltiradi: u `catalog_product_code` ga yozadi, ya'ni har yurishda
-- qator yaratadi.
--
-- YECHIM: navbat IKKI MANBADAN oziqlanadi va ikkinchisi HECH NARSA
-- YOZMAYDI -- u tahlil jadvalining o'zidan o'qiydi. `catalog_kod_tahlil`
-- `(company_id, product_id)` bo'yicha UPSERT qilinadi, shuning uchun
-- takror yurish dublikat YARATA OLMAYDI -- bu mexanizmning xossasi,
-- tartib-intizom masalasi emas.
--
--     manba='faol'    tasdiqlangan, lekin siyosat shubhali deb belgilagan
--     manba='taklif'  hali kod yo'q; tahlil nomzod topdi, siyosat
--                     avtomatik tasdiqqa yetarli emas dedi
--
-- INSON QARORI QAYTA CHIQMAYDI: mahsulotda odam tasdiqlagan aniq kod
-- bo'lsa yoki taklif rad etilgan bo'lsa, u `taklif` tarmog'iga
-- TUSHMAYDI.
-- =============================================================================

ALTER TABLE catalog_kod_tahlil
    ADD COLUMN IF NOT EXISTS siyosat_qaror TEXT,
    ADD COLUMN IF NOT EXISTS siyosat_sabab TEXT;

COMMENT ON COLUMN catalog_kod_tahlil.siyosat_qaror IS
    'Avtomatik tasdiq siyosatining qarori: auto | navbat | kodsiz. '
    '`sabab` dan FARQLI: `sabab` algoritm nima topganini, bu esa '
    'unga inson nazoratisiz ishonish mumkinmi degan savolga javob.';

CREATE INDEX IF NOT EXISTS catalog_kod_tahlil_navbat_idx
    ON catalog_kod_tahlil (company_id, product_id)
    WHERE siyosat_qaror = 'navbat';

-- ---------------------------------------------------------------------------
-- KO'RIK NAVBATI — IKKI MANBA
-- `manba` ustuni OXIRIGA qo'shiladi: CREATE OR REPLACE mavjud
-- ustunlarning tartibini o'zgartirishga yo'l qo'ymaydi.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_catalog_kod_korik AS
SELECT pc.company_id,
       pc.product_id,
       p.name          AS mahsulot,
       pc.code,
       pc.tasdiqlagan,
       pc.tasdiqlandi,
       pc.siyosat_sabab,
       pc.siyosat_at,
       COALESCE(t.ochiq_tender, 0) AS ochiq_tender,
       'faol'::text    AS manba
  FROM catalog_product_code pc
  JOIN catalog_product p
    ON p.id = pc.product_id AND p.company_id = pc.company_id
  LEFT JOIN catalog_kod_tahlil t
    ON t.product_id = pc.product_id AND t.company_id = pc.company_id
 WHERE pc.korib_chiqilsin
   AND pc.tasdiqlandi IS NOT NULL
   AND pc.rad_etildi IS NULL

UNION ALL

SELECT t.company_id,
       t.product_id,
       p.name          AS mahsulot,
       t.taklif_code   AS code,
       NULL::text      AS tasdiqlagan,
       NULL::timestamptz AS tasdiqlandi,
       t.siyosat_sabab,
       t.tahlil_at     AS siyosat_at,
       COALESCE(t.ochiq_tender, 0) AS ochiq_tender,
       'taklif'::text  AS manba
  FROM catalog_kod_tahlil t
  JOIN catalog_product p
    ON p.id = t.product_id AND p.company_id = t.company_id
 WHERE t.siyosat_qaror = 'navbat'
   AND t.taklif_code IS NOT NULL
   -- MAHSULOTDA FAOL ANIQ KOD BO'LSA -- bu yo'l EMAS. Bunday holat
   -- birinchi tarmoqda (`faol`) ko'rinadi yoki umuman ko'rilmaydi.
   AND NOT EXISTS (
        SELECT 1 FROM v_catalog_code_active v
         WHERE v.product_id = t.product_id
           AND v.company_id = t.company_id
           AND length(v.code) >= 8)
   -- INSON QARORI QAYTA CHIQMAYDI: rad etilgan taklif navbatga
   -- qaytmaydi, aks holda odam bir ishni takror qilardi.
   AND NOT EXISTS (
        SELECT 1 FROM catalog_product_code r
         WHERE r.product_id = t.product_id
           AND r.company_id = t.company_id
           AND r.code = t.taklif_code
           AND r.rad_etildi IS NOT NULL);

COMMENT ON VIEW v_catalog_kod_korik IS
    'Ko''rik navbati. `manba=faol` — tasdiqlangan, lekin shubhali '
    'deb belgilangan kod (faolligi saqlanadi). `manba=taklif` — hali '
    'kod yo''q, tahlil nomzod topdi, siyosat avtomatik tasdiqqa '
    'yetarli emas dedi. Ikkinchi tarmoq HECH NARSA YOZMAYDI.';
