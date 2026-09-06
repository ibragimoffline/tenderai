-- =====================================================================
-- SUHBAT TIKLANISHI O'LCHANADI — "24 soat to'g'ri chegarami?"
-- =====================================================================
--
-- 2026-09-04 da `ChatPanel` ochilganda oxirgi suhbatni davom
-- ettiradigan bo'ldi (`DAVOM_SOAT = 24`). Chegara O'LCHANMAGAN
-- TAXMIN: 24 raqami hech qanday ma'lumotdan chiqmagan.
--
-- XAVF ANIQ: tender suhbati uchun 24 soat oz bo'lishi mumkin
-- (tender bir necha kun ochiq turadi), global suhbat uchun esa
-- KO'P — foydalanuvchi ertalab boshqa mavzuda gaplashgan bo'lsa,
-- kechqurun "Oldingi suhbat davom etmoqda — 9 ta xabar eslanadi"
-- ni ko'radi va tushunmaydi.
--
-- "Yangi suhbat" tugmasi bu holatdan chiqish yo'li. Ya'ni U
-- BOSILGANI — o'lchov: chegara noto'g'ri ekanining signali.
--
--     tiklandi_at      panelga tiklandi
--     tiklash_rad_at   foydalanuvchi "Yangi suhbat" bosdi
--
-- NEGA IKKITA USTUN, BITTA BAYROQ EMAS: maxraj kerak. "10 marta
-- rad etildi" o'zicha hech narsa demaydi — 10/12 bilan 10/500
-- boshqa xulosa beradi. Bu loyihada takrorlangan xato
-- (`kelishuv_foiz` maxrajsiz hisoblangani).
--
-- Qo'llash:
--   .venv\Scripts\python.exe migratsiya.py --qolla
-- =====================================================================

BEGIN;

ALTER TABLE chat_session
    ADD COLUMN IF NOT EXISTS tiklandi_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS tiklash_rad_at TIMESTAMPTZ;

-- RAD ETISH TIKLANISHSIZ BO'LMAYDI. Aks holda maxraj surat'dan
-- kichik bo'lib, foiz 100 dan oshib ketardi.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'chat_session_tiklash_chk') THEN
        ALTER TABLE chat_session ADD CONSTRAINT chat_session_tiklash_chk
            CHECK (tiklash_rad_at IS NULL OR tiklandi_at IS NOT NULL);
    END IF;
END $$;

-- --- O'LCHOV KO'RINISHI ------------------------------------------------
--
-- KESIM: global va tenderli ALOHIDA. Butun savol shu — bitta
-- chegara ikkalasiga ham to'g'ri keladimi.
--
-- `eval` sessiyalari CHIQARIB TASHLANADI: ular tiklanmaydi ham,
-- lekin kelajakda `manba` bo'yicha filtrsiz qolsa o'lchovni
-- ifloslantirardi (§ `schema_patch_chat_manba.sql`).
CREATE OR REPLACE VIEW v_chat_tiklash AS
SELECT
    company_id,
    CASE WHEN tender_id IS NULL THEN 'global' ELSE 'tender' END AS kesim,
    count(*) FILTER (WHERE tiklandi_at IS NOT NULL)     AS tiklandi,
    count(*) FILTER (WHERE tiklash_rad_at IS NOT NULL)  AS rad_etildi,
    -- NOL MAXRAJDA NULL — NOL EMAS. "0% rad etildi" hech narsa
    -- tiklanmagan holatni "chegara mukammal" deb ko'rsatardi.
    round(100.0 * count(*) FILTER (WHERE tiklash_rad_at IS NOT NULL)
          / NULLIF(count(*) FILTER (WHERE tiklandi_at IS NOT NULL), 0), 1)
        AS rad_foiz,
    -- Tiklangandan rad etilgunicha o'tgan vaqt: tez rad etilsa
    -- foydalanuvchi kontekstni umuman kutmagan degani.
    round(avg(EXTRACT(EPOCH FROM (tiklash_rad_at - tiklandi_at)))
          FILTER (WHERE tiklash_rad_at IS NOT NULL))::int
        AS ortacha_sek
FROM chat_session
WHERE manba IS DISTINCT FROM 'eval'
GROUP BY company_id, 2;

COMMENT ON VIEW v_chat_tiklash IS
    'Suhbat tiklanishi qabul qilindimi. `rad_foiz` yuqori bo`lsa '
    '`DAVOM_SOAT` chegarasi o`sha kesim uchun noto`g`ri. Global va '
    'tenderli ALOHIDA — bitta chegara ikkalasiga to`g`ri kelmasligi '
    'mumkin. Maxraj nol bo`lsa foiz NULL, nol EMAS.';

-- --- MUSBAT TASDIQ ----------------------------------------------------
DO $$
BEGIN
    IF to_regclass('public.v_chat_tiklash') IS NULL THEN
        RAISE EXCEPTION 'v_chat_tiklash yaratilmadi';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='chat_session'
                      AND column_name='tiklash_rad_at') THEN
        RAISE EXCEPTION 'tiklash_rad_at yaratilmadi';
    END IF;
END $$;

COMMIT;

-- =====================================================================
-- ROLLBACK (qo'lda):
--   DROP VIEW IF EXISTS v_chat_tiklash;
--   ALTER TABLE chat_session DROP CONSTRAINT IF EXISTS chat_session_tiklash_chk;
--   ALTER TABLE chat_session DROP COLUMN IF EXISTS tiklandi_at,
--                            DROP COLUMN IF EXISTS tiklash_rad_at;
-- =====================================================================
