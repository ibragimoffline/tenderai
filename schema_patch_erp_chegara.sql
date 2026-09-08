-- =====================================================================
-- ERP CHEGARASINI QAYTA O'RNATISH — OLDINGA MIGRATSIYA
-- =====================================================================
-- O'LCHANGAN SILJISH (2026-09-09, izolyatsiyalangan darvoza):
--
--     tai_app ga `erp` sxemasida 41 obyektga SELECT berilgan edi:
--       34 jadval + 7 ko'rinish.
--     Ruxsat etilgani esa BESHTA ko'rinish.
--
-- Ortiqchalar ichida: `app_user` (parol xeshlari), `app_session`
-- (sessiya tokenlari), `login_attempt`, `contract`, `invoice`,
-- `invoice_payment`, `client_company`, `client_contact`,
-- `client_document`, `chat_message`, `chat_message_history`,
-- `doc_audit`, `setting`, `own_company`.
--
-- ILDIZ SABAB — SUKUT HUQUQ, bir martalik grant EMAS:
--
--     egasi=tai_owner  erp  r  tai_app  SELECT
--
-- Ya'ni `ALTER DEFAULT PRIVILEGES ... IN SCHEMA erp` qo'yilgan va
-- `tai_owner` yaratgan HAR YANGI ERP jadvali avtomatik ochilgan.
-- Faqat `REVOKE` qilish YETARLI EMAS: keyingi ERP migratsiyasi
-- siljishni QAYTA yaratardi.
--
-- `schema_patch_huquq.sql` ning o'zi buning aksini yozadi:
--   "Kelajakdagi ERP jadvallariga AVTOMATIK huquq BERILMAYDI:
--    default privilege ATAYLAB qo'yilmaydi."
-- Demak sukut huquq loyiha qaroriga ZID va u o'chiriladi.
--
-- NEGA YANGI PATCH, ESKISINI TAHRIRLASH EMAS: `0057_huquq`
-- qo'llangan. Uni o'zgartirish tarixni qayta muhrlashni talab
-- qilardi va `migratsiya.py` ning o'z qoidasi shuni taqiqlaydi:
-- "Agar sxemaga TEGSA — YANGI patch fayli yozing."
--
-- IDEMPOTENT: bir necha marta yurgizsa bo'ladi.
-- FAIL CLOSED: oxirida ortiqcha huquq qolsa migratsiya TO'XTAYDI.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- Ruxsat etilgan shartnoma ko'rinishlari — YAGONA MANBA
-- ---------------------------------------------------------------------
-- Ro'yxat `schema_patch_erp_19.sql` (ERP tomoni) bilan bir xil.
-- Naqsh (`v_*`) ISHLATILMAYDI: `v_hodim_yuklama` va
-- `v_notification_health` ham `v_` bilan boshlanadi, lekin ular
-- shartnomaga KIRMAYDI va aynan shu ikkitasi ortiqcha edi.
CREATE TEMP TABLE _erp_ruxsat (nom TEXT PRIMARY KEY) ON COMMIT DROP;
INSERT INTO _erp_ruxsat (nom) VALUES
    ('v_tai_actor'),
    ('v_tender_status'),
    ('v_stock'),
    ('v_stock_balance'),
    ('v_client_document');

DO $$
DECLARE
    ortiqcha TEXT;
    n        INT;
    v        TEXT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.schemata
                   WHERE schema_name = 'erp') THEN
        RAISE NOTICE 'erp sxemasi yo''q — chegara o''rnatilmadi.';
        RETURN;
    END IF;

    -- 1) KELAJAKDAGI SILJISH TO'XTATILADI.
    -- Bu BIRINCHI qadam: agar quyidagi tozalashdan keyin qo'yilsa,
    -- oradagi yangi jadval yana ochiq qolardi.
    EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE tai_owner IN SCHEMA erp '
            'REVOKE SELECT ON TABLES FROM tai_app';
    EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE tai_owner IN SCHEMA erp '
            'REVOKE ALL ON SEQUENCES FROM tai_app';
    EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE tai_owner IN SCHEMA erp '
            'REVOKE ALL ON FUNCTIONS FROM tai_app';
    RAISE NOTICE 'erp sukut huquqlari olib tashlandi (tai_owner).';

    -- 2) HOZIRGI SILJISH TOZALANADI.
    -- HAMMASI olib tashlanadi, keyin FAQAT ro'yxatdagilar qaytariladi.
    -- "Ortiqchalarini sanab REVOKE qilish" yo'li kelajakda yangi
    -- obyekt qo'shilsa jimgina orqada qolardi.
    REVOKE ALL ON ALL TABLES    IN SCHEMA erp FROM tai_app;
    REVOKE ALL ON ALL SEQUENCES IN SCHEMA erp FROM tai_app;
    REVOKE ALL ON ALL FUNCTIONS IN SCHEMA erp FROM tai_app;
    REVOKE CREATE ON SCHEMA erp FROM tai_app;

    -- 3) SHARTNOMA QAYTARILADI.
    -- `USAGE` KERAK: usiz ko'rinishlar ham o'qilmaydi.
    GRANT USAGE ON SCHEMA erp TO tai_app;
    FOR v IN SELECT nom FROM _erp_ruxsat LOOP
        IF to_regclass('erp.' || quote_ident(v)) IS NOT NULL THEN
            EXECUTE format('GRANT SELECT ON erp.%I TO tai_app', v);
        ELSE
            RAISE NOTICE 'erp.% hali yo''q — o''tkazildi.', v;
        END IF;
    END LOOP;

    -- 4) FAIL CLOSED — NATIJA O'LCHANADI.
    -- Migratsiya "men REVOKE yubordim" deb emas, "ortiqcha huquq
    -- QOLMADI" deb tugashi kerak. Ikkisi bir xil emas: `PUBLIC`,
    -- rol a'zoligi yoki boshqa grant yo'li orqali huquq qolishi
    -- mumkin va u JIMGINA o'tib ketardi.
    SELECT count(*), string_agg(c.relname, ', ' ORDER BY c.relname)
      INTO n, ortiqcha
      FROM pg_class c
      JOIN pg_namespace ns ON ns.oid = c.relnamespace
     WHERE ns.nspname = 'erp'
       AND c.relkind IN ('r', 'v', 'm', 'p', 'f')
       AND has_table_privilege('tai_app', c.oid, 'SELECT')
       AND c.relname NOT IN (SELECT nom FROM _erp_ruxsat);

    IF n > 0 THEN
        RAISE EXCEPTION
            'ERP CHEGARASI O''RNATILMADI: tai_app hamon % ta ortiqcha '
            'obyektni o''qiy oladi: %', n, left(ortiqcha, 300)
            USING HINT = 'Boshqa grant yo''li bor: PUBLIC, rol a''zoligi '
                         'yoki egalik. `aclexplode` bilan tekshiring.';
    END IF;

    RAISE NOTICE 'ERP chegarasi o''rnatildi: ortiqcha huquq 0.';
END $$;

COMMIT;
