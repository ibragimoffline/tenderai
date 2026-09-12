-- =============================================================================
-- KOD SIYOSATI — QAYTA BAHOLASH FAOLLIKNI BEKOR QILMAYDI
--
--   psql "dbname=xtxarid user=postgres host=localhost" -f schema_patch_kod_siyosat.sql
--
-- MUAMMO
-- ------
-- 2026-09-12 da 187 ta kod avtomatik faollashtirildi. O'SHANDAN KEYIN
-- avtomatik tasdiq siyosati (`catalog_auto.siyosat_qarori`) va bosh so'z
-- ziddiyati signali yozildi. Yangi siyosat bilan qayta baholaganda 187
-- tadan 138 tasi o'tadi, 49 tasi o'tmaydi.
--
-- O'TMAGANLARNI DARHOL O'CHIRISH NOTO'G'RI BO'LARDI. Ular orasida
-- haqiqiy xato bor (server SHKAFI `Сервер` deb kodlangan), lekin
-- hammasi xato degani emas -- yangi siyosat qat'iyroq, xatosiz emas.
-- Faollikni birdan bekor qilish "Sizga mos" ni 49 mahsulot bo'yicha
-- keskin kamaytirardi va TO'G'RI kodlarni ham yo'qotardi.
--
-- YECHIM: BAHO va FAOLLIK ikki alohida narsa.
--
--     korib_chiqilsin = true   -- siyosatdan o'tmadi, ODAM KO'RSIN
--     tasdiqlandi              -- TEGILMAYDI, kod ishlashda qoladi
--
-- Bog'lanish FAQAT inson rad etganda yoki boshqa kod tanlaganda
-- o'zgaradi.
--
-- ORQAGA MOSLIK: ikkala ustun ham DEFAULT bilan qo'shiladi; eski
-- yozuvlar `korib_chiqilsin = false` bo'lib qoladi va hech bir
-- mavjud so'rov o'zgarmaydi.
-- =============================================================================

ALTER TABLE catalog_product_code
    ADD COLUMN IF NOT EXISTS korib_chiqilsin BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS siyosat_sabab   TEXT,
    ADD COLUMN IF NOT EXISTS siyosat_at      TIMESTAMPTZ;

COMMENT ON COLUMN catalog_product_code.korib_chiqilsin IS
    'Avtomatik tasdiq siyosatidan O''TMADI -- odam ko''rib chiqsin. '
    'FAOLLIKKA TA''SIR QILMAYDI: `tasdiqlandi` o''z holicha qoladi va '
    'kod ishlashda davom etadi. Bog''lanish faqat inson rad etganda '
    'yoki boshqa kod tanlaganda o''zgaradi.';
COMMENT ON COLUMN catalog_product_code.siyosat_sabab IS
    'QAYSI tekshiruv yiqilgani (masalan `siyosat:dalil,ziddiyat`). '
    'Odam ko''rib chiqishda NEGA belgilanganini bilishi kerak.';

-- Qamrov so'rovlari faqat belgilanganlarni oladi -- qisman indeks.
CREATE INDEX IF NOT EXISTS catalog_product_code_korik_idx
    ON catalog_product_code (company_id, product_id)
    WHERE korib_chiqilsin;

-- ---------------------------------------------------------------------------
-- KO'RIK NAVBATI — belgilangan FAOL kodlar, biznes qiymati bo'yicha
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
       COALESCE(t.ochiq_tender, 0) AS ochiq_tender
  FROM catalog_product_code pc
  JOIN catalog_product p
    ON p.id = pc.product_id AND p.company_id = pc.company_id
  LEFT JOIN catalog_kod_tahlil t
    ON t.product_id = pc.product_id AND t.company_id = pc.company_id
 WHERE pc.korib_chiqilsin
   AND pc.tasdiqlandi IS NOT NULL
   AND pc.rad_etildi IS NULL;

COMMENT ON VIEW v_catalog_kod_korik IS
    'Siyosatdan o''tmagan, LEKIN hali FAOL kodlar. Ular ishlashda '
    'davom etadi; bu ro''yxat odam ko''rib chiqishi uchun.';
