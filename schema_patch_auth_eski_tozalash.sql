-- =====================================================================
-- ESKI `public.app_user` / `public.app_session` NI TOZALASH
-- =====================================================================
-- KELIB CHIQISHI. `schema_patch_auth_2.sql` bu jadvallarni SHARTLI
-- tushiradi: `erp.app_user` BO'SH bo'lsa ularni QOLDIRADI va
-- ogohlantiradi. Bu to'g'ri qaror edi -- ko'chirilmagan hisoblarni
-- yo'qotmaslik uchun.
--
-- O'LCHANGAN (2026-09-09, izolyatsiyalangan darvoza):
--
--     public.app_user   mavjud: true   qatorlar: 0
--     erp.app_user      qatorlar: 0
--     FK: app_session.app_session_user_id_fkey
--     bog'liq view/funksiya: yo'q
--
-- Ya'ni eski jadval BO'SH. "Eski parol xeshlari saqlanib turibdi"
-- degan taxmin O'LCHOV BILAN RAD ETILDI: yo'qotadigan ma'lumot yo'q.
--
-- `erp.app_user` ham bo'sh, shuning uchun eski migratsiyaning sharti
-- (`moved > 0`) HAMON bajarilmaydi va u hech qachon o'zi tushirmaydi.
--
-- NEGA SHART KENGAYTIRILDI. Eski shart "ERP da hisob bor" edi. To'g'ri
-- shart esa "MA'LUMOT YO'QOLMAYDI", va u ikki yo'l bilan qondiriladi:
--     a) eski jadval BO'SH                  -> yo'qotadigan narsa yo'q
--     b) yoki har bir eski hisob ERP da BOR -> ko'chirilgan
-- Ikkalasi ham bajarilmasa migratsiya TO'XTAYDI.
--
-- AUTENTIFIKATSIYA BU JADVALLARNI ISHLATMAYDI (o'lchandi):
-- `api/auth.py` hisoblarni `company_account` dan, sessiyalarni
-- `company_session` dan o'qiydi. `app_user` faqat izohlarda tilga
-- olinadi.
--
-- `CASCADE` ISHLATILMAYDI. Bog'liqliklar oldindan sanaladi va
-- kutilmagani bo'lsa migratsiya to'xtaydi. `CASCADE` "nima
-- o'chganini" jimgina yashirardi.
--
-- IDEMPOTENT. Jadval yo'q bo'lsa hech nima qilinmaydi.
-- =====================================================================

BEGIN;

DO $$
DECLARE
    n_eski      INT := 0;
    n_erp       INT := 0;
    n_kochmagan INT := 0;
    n_ikkilan   INT := 0;
    n_begona    INT := 0;
    begona      TEXT;
BEGIN
    IF to_regclass('public.app_user') IS NULL THEN
        RAISE NOTICE 'public.app_user yo''q — tozalash kerak emas.';
        RETURN;
    END IF;

    SELECT count(*) INTO n_eski FROM public.app_user;

    -- --- SHART (b) UCHUN ERP KERAK -----------------------------------
    IF n_eski > 0 THEN
        IF to_regclass('erp.app_user') IS NULL THEN
            RAISE EXCEPTION
                'ESKI JADVALDA % ta hisob bor, `erp.app_user` esa YO''Q '
                '— ko''chirish tekshirib bo''lmaydi.', n_eski
                USING HINT = 'Avval schema_patch_erp_6.sql ni qo''llang.';
        END IF;

        SELECT count(*) INTO n_erp FROM erp.app_user;

        -- KO'CHMAGANLAR. Kimlik `username` bo'yicha, registrsiz.
        -- ID lar TAQQOSLANMAYDI: ikki tizimda ular mustaqil.
        SELECT count(*) INTO n_kochmagan
          FROM public.app_user l
         WHERE NOT EXISTS (SELECT 1 FROM erp.app_user e
                            WHERE lower(e.username) = lower(l.username));

        -- IKKILANGAN MOSLIK. Bitta eski nom ERP da bir nechta hisobga
        -- tushsa, "ko'chirilgan" degan xulosa ASOSSIZ bo'lardi.
        SELECT count(*) INTO n_ikkilan FROM (
            SELECT lower(l.username)
              FROM public.app_user l
              JOIN erp.app_user e ON lower(e.username) = lower(l.username)
             GROUP BY 1 HAVING count(*) > 1) q;

        IF n_kochmagan > 0 OR n_ikkilan > 0 THEN
            RAISE EXCEPTION
                'KO''CHIRISH TUGALLANMAGAN: ko''chmagan=% ikkilangan=% '
                '(eski=%, erp=%)', n_kochmagan, n_ikkilan, n_eski, n_erp
                USING HINT = 'Jadval QOLDIRILDI. Hisoblar qo''lda '
                             'ko''chirilsin; parol xeshlari CHOP '
                             'ETILMAYDI.';
        END IF;
    END IF;

    -- --- BOG'LIQLIK AUDITI -------------------------------------------
    -- KUTILGAN yagona bog'liqlik — `public.app_session`. Boshqasi
    -- bo'lsa u AUDIT QILINMAGAN va tushirish to'xtaydi.
    SELECT count(*), string_agg(src.relname, ', ')
      INTO n_begona, begona
      FROM pg_constraint c
      JOIN pg_class t   ON t.oid = c.confrelid
      JOIN pg_class src ON src.oid = c.conrelid
      JOIN pg_namespace n ON n.oid = t.relnamespace
     WHERE c.contype = 'f'
       AND n.nspname = 'public' AND t.relname = 'app_user'
       AND src.relname <> 'app_session';

    IF n_begona > 0 THEN
        RAISE EXCEPTION
            'KUTILMAGAN BOG''LIQLIK: % ta jadval `public.app_user` ga '
            'bog''langan: %', n_begona, begona
            USING HINT = 'Ular audit qilinmagan. `CASCADE` ISHLATILMAYDI.';
    END IF;

    -- View/funksiya bog'liqligi ham bo'lmasligi kerak.
    SELECT count(*), string_agg(DISTINCT dep.relname, ', ')
      INTO n_begona, begona
      FROM pg_depend d
      JOIN pg_rewrite r  ON r.oid = d.objid
      JOIN pg_class dep  ON dep.oid = r.ev_class
      JOIN pg_class src  ON src.oid = d.refobjid
      JOIN pg_namespace n ON n.oid = src.relnamespace
     WHERE n.nspname = 'public' AND src.relname = 'app_user'
       AND dep.relname NOT IN ('app_user', 'app_session');

    IF n_begona > 0 THEN
        RAISE EXCEPTION
            'KO''RINISH/QOIDA BOG''LIQLIGI: %', begona
            USING HINT = 'Avval ular ko''rib chiqilsin.';
    END IF;

    -- --- TUSHIRISH — RESTRICT ----------------------------------------
    -- `app_session` AVVAL: u `app_user` ga FK bilan bog'langan.
    -- `RESTRICT` ataylab: kutilmagan bog'liqlik qolsa PostgreSQL
    -- to'xtatadi va biz buni KO'RAMIZ.
    DROP TABLE IF EXISTS public.app_session RESTRICT;
    DROP TABLE IF EXISTS public.app_user RESTRICT;

    RAISE NOTICE 'Eski auth jadvallari olib tashlandi '
                 '(eski=% erp=% ko''chmagan=0 ikkilangan=0).', n_eski, n_erp;
END $$;

COMMIT;
