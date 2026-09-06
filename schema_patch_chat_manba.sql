-- =====================================================================
-- CHAT SESSIYASINING MANBASI — "bu suhbat qayerdan boshlangan"
-- =====================================================================
--
-- O'LCHANGAN MUAMMO (2026-09-04). `chat_session` da 133 qator bor va
-- ularning 122 tasi `_tests/ai_eval/run_eval.py` YURISHIDAN. Eval
-- `EVAL_COMPANY_ID = 2` bilan ishlaydi — bu HAQIQIY ijarachining
-- o'zi. Ya'ni avto-yaratilgan ma'lumot inson hovuzida turibdi va
-- jurnalni faqat sarlavhadagi `[eval]` prefiksi bo'yicha ajratish
-- mumkin edi.
--
-- Bu jimgina xato chiqardi: "133 sessiya / 245 xabar -> 2 xabar
-- sessiyaga -> foydalanuvchi savol-javob rejimida ishlaydi" degan
-- xulosa chiqarilgan edi. Aslida 2 xabar — benchmark skriptining
-- xulqi (har savolga yangi sessiya), foydalanuvchining emas.
-- Rejaning butun bir bo'limi (§3.2 qaror jadvali) shu raqamga
-- qurilgan edi.
--
-- YECHIM: manba JURNALDA belgilanadi, taxmin qilinmaydi.
--
-- IKKINCHI USTUN — `tahlil_hash`: sessiya ochilgandagi
-- `ai_analysis.content_hash`. U bilan "tahlil sessiya
-- boshlangandan beri o'zgardimi" savoliga javob beriladi
-- (`tender_routing.ai_ozgardi` bilan bir tamoyil: inson eski
-- ma'lumotga qarab qaror qilmasin).
--
-- Qo'llash:
--   .venv\Scripts\python.exe migratsiya.py --apply
-- yoki:
--   psql "$XT_DB_DSN" -f schema_patch_chat_manba.sql
-- =====================================================================

BEGIN;

ALTER TABLE chat_session
    ADD COLUMN IF NOT EXISTS manba       TEXT,
    ADD COLUMN IF NOT EXISTS tahlil_hash TEXT;

-- MANBA QIYMATLARI — YOPIQ RO'YXAT.
--
--   eval    `_tests/ai_eval/run_eval.py` — INSON EMAS
--   gonogo  Go/No-Go panelidan "bu tahlil haqida so'rang"
--   match   moslik panelidan
--   panel   tender panelidan ochilgan suhbat
--   global  suzuvchi tugmadan, tender konteksti yo'q
--
-- `NULL` ATAYLAB RUXSAT ETILADI: eski qatorlar va manbani
-- aytmagan chaqiruvchilar. "Noma'lum" ni "global" ga aylantirish
-- bu loyihada eng qimmat xato sinfi (o'lchanmaganni o'lchangan
-- deb ko'rsatish).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'chat_session_manba_chk') THEN
        ALTER TABLE chat_session ADD CONSTRAINT chat_session_manba_chk
            CHECK (manba IS NULL OR manba IN
                   ('eval', 'gonogo', 'match', 'panel', 'global'));
    END IF;
END $$;

-- --- BACKFILL ---------------------------------------------------------
--
-- FAQAT ISHONCHLI BELGI ishlatiladi. `run_eval.py` sarlavhani
-- `[eval] <case_id>` qilib yozadi — bu skriptning o'zidagi format,
-- taxmin emas.
UPDATE chat_session SET manba = 'eval'
 WHERE manba IS NULL AND title LIKE '[eval]%';

-- Qolganlari uchun manba ANIQ EMAS: interfeys uni hech qachon
-- yozmagan. `tender_id` bor/yo'qligi "panel/global" ni TAXMIN
-- qilardi, lekin tender konteksti global suhbatda ham
-- bo'lishi mumkin edi. Shuning uchun ular `NULL` QOLADI va
-- o'lchovda "noma'lum" deb sanaladi.

CREATE INDEX IF NOT EXISTS chat_session_manba_idx
    ON chat_session (company_id, manba, updated_at DESC);

-- --- MUSBAT TASDIQ ----------------------------------------------------
DO $$
DECLARE n_eval INT; n_null INT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='chat_session' AND column_name='manba') THEN
        RAISE EXCEPTION 'chat_session.manba yaratilmadi';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='chat_session' AND column_name='tahlil_hash') THEN
        RAISE EXCEPTION 'chat_session.tahlil_hash yaratilmadi';
    END IF;
    SELECT count(*) FILTER (WHERE manba='eval'),
           count(*) FILTER (WHERE manba IS NULL)
      INTO n_eval, n_null FROM chat_session;
    RAISE NOTICE 'chat_session: % ta eval belgilandi, % ta noma`lum qoldi',
                 n_eval, n_null;
END $$;

COMMENT ON COLUMN chat_session.manba IS
    'Suhbat qayerdan boshlangan: eval|gonogo|match|panel|global. '
    '`eval` — AVTO-YARATILGAN, inson o`lchoviga KIRMAYDI. NULL — '
    'noma`lum (interfeys manbani yozmagan davr).';
COMMENT ON COLUMN chat_session.tahlil_hash IS
    'Sessiya ochilgandagi ai_analysis.content_hash. Farq bo`lsa '
    'tahlil eskirgan — foydalanuvchiga aytiladi.';

COMMIT;

-- =====================================================================
-- ROLLBACK (qo'lda):
--   ALTER TABLE chat_session DROP CONSTRAINT IF EXISTS chat_session_manba_chk;
--   DROP INDEX IF EXISTS chat_session_manba_idx;
--   ALTER TABLE chat_session DROP COLUMN IF EXISTS manba,
--                            DROP COLUMN IF EXISTS tahlil_hash;
-- =====================================================================
