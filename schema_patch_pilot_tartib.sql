-- =============================================================================
-- schema_patch_pilot_tartib.sql  —  0076 NING TUGALLANMAGAN QISMI
--
-- 0076 (`pilot_avlod`) BIRLAMCHI KALITNI `(company_id, avlod, tender_id)`
-- ga o'tkazdi, LEKIN ikkinchi unikal indeksni unutdi:
--
--     review_pilot_tartib_idx  UNIQUE (company_id, tartib)
--
-- `tartib` har avlodda 1 dan boshlanadi. Shu indeks bilan IKKINCHI
-- AVLOD UMUMAN YARATILMASDI — birinchi qatorning `tartib = 1` i
-- 1-avloddagi `tartib = 1` bilan to'qnashardi.
--
-- Ya'ni 0076 muammoni yarim hal qilgan bo'lardi: kod yangi avlod
-- ochishga ruxsat berardi, baza esa uni JIMGINA rad etardi
-- (`ON CONFLICT DO NOTHING` sabab XATO ham chiqmasdi — qatorlar
-- shunchaki yozilmasdi va pilot BO'SH bo'lib qolardi).
--
-- Buni mavjud sinov (`_tests/requirement_test.py`, "takror tartib
-- yo'q") ko'rsatdi — u ham `(company_id, tartib)` bo'yicha
-- guruhlaydi va u ham shu patchda yangilanadi.
-- =============================================================================

\set ON_ERROR_STOP on

BEGIN;

DROP INDEX IF EXISTS review_pilot_tartib_idx;

-- TARTIB AVLOD ICHIDA noyob. Avlodlar orasida takrorlanishi SHART —
-- har pilot o'z 1..N tartibini oladi.
CREATE UNIQUE INDEX review_pilot_tartib_idx
    ON review_pilot (company_id, avlod, tartib);

COMMENT ON INDEX review_pilot_tartib_idx IS
    'Tartib AVLOD ICHIDA noyob. Ilgari `(company_id, tartib)` edi va '
    'u ikkinchi avlodni butunlay to''sardi.';

-- ---------------------------------------------------------------------
-- TEKSHIRUV — ikkinchi avlod HAQIQATAN yoziladimi
-- ---------------------------------------------------------------------
-- "Indeks o'zgardi" YETARLI EMAS (2-sinf: salbiy shartdan xulosa).
-- Haqiqiy yozuvni sinab ko'ramiz va ORQAGA QAYTARAMIZ.
DO $$
DECLARE cid INT; tid BIGINT; n INT;
BEGIN
    SELECT company_id, tender_id INTO cid, tid
      FROM review_pilot ORDER BY company_id, avlod, tartib LIMIT 1;
    IF cid IS NULL THEN
        RAISE NOTICE 'review_pilot bo''sh — sinab ko''rish o''tkazildi.';
        RETURN;
    END IF;

    INSERT INTO review_pilot_avlod (company_id, avlod, yaratgan, izoh)
    VALUES (cid, 9999, 'tekshiruv', 'patch tekshiruvi — o''chiriladi');
    INSERT INTO review_pilot (company_id, avlod, tender_id, guruh, rejim, tartib)
    VALUES (cid, 9999, tid, 'tasodif', 'blind', 1);

    SELECT count(*) INTO n FROM review_pilot
     WHERE company_id = cid AND avlod = 9999;
    IF n <> 1 THEN
        RAISE EXCEPTION 'ikkinchi avlod YOZILMADI — indeks hali to''sadi';
    END IF;

    DELETE FROM review_pilot       WHERE company_id = cid AND avlod = 9999;
    DELETE FROM review_pilot_avlod WHERE company_id = cid AND avlod = 9999;
    RAISE NOTICE 'TEKSHIRUV O''TDI — ikkinchi avlod yoziladi va tozalandi.';
END $$;

COMMIT;


-- =============================================================================
-- ROLLBACK:
--   DROP INDEX IF EXISTS review_pilot_tartib_idx;
--   CREATE UNIQUE INDEX review_pilot_tartib_idx
--       ON review_pilot (company_id, tartib);
-- =============================================================================
