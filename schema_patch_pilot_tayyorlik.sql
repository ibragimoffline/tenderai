-- =============================================================================
-- PILOT TAYYORLIGI — "nega aktorli qaror chiqmayapti" savoliga javob
--
--   psql "dbname=xtxarid user=postgres host=localhost" -f schema_patch_pilot_tayyorlik.sql
--
-- O'LCHANGAN NUQSON (2026-09-02)
-- ------------------------------
-- 0069 sifat darvozasini qo'ydi va u FAQAT `aktorli` qarorni
-- sanaydi (kim qaror qilgani ma'lum bo'lganini). Darvoza to'g'ri,
-- lekin u "0" ni ko'rsatadi va SABABINI aytmaydi.
--
-- Sabab o'lchandi:
--
--     kompaniya   aktor   faol
--     2 (asosiy)      0      0     <-- pilot shu yerda yuradi
--     199             1      0
--     200             4      0
--     271             2      0
--     272             1      0
--
-- Ya'ni asosiy kompaniyada BITTA HAM aktor yo'q. Interfeys
-- `X-Actor` sarlavhasini yuboradi (`frontend/src/api.ts`), lekin
-- tanlash uchun ro'yxat BO'SH. Natijada har qaror
-- `kompaniya_sessiyasi` darajasida yoziladi — ya'ni ODAM qildi,
-- lekin QAYSI odam ekani noma'lum.
--
-- Bu holat JIMGINA yuz beradi: ko'ruvchi ishlaydi, qarorlar
-- yoziladi, hisoblagich esa 0 da turadi va hech kim nima uchunligini
-- bilmaydi. Pilotni boshlashdan OLDIN ko'rinishi kerak.
--
-- BU KO'RINISH PILOTNI TAYYORLAMAYDI — u faqat NIMA YETISHMAYOTGANINI
-- aytadi. Aktor qo'shish MA'MURIY amal (haqiqiy odam ismi) va u
-- `POST /aktor` orqali qilinadi; bu migratsiya aktor YARATMAYDI.
-- =============================================================================

BEGIN;

DROP VIEW IF EXISTS v_pilot_tayyorlik CASCADE;
CREATE VIEW v_pilot_tayyorlik AS
WITH aktorlar AS (
    SELECT company_id,
           count(*) AS aktor_jami,
           count(*) FILTER (WHERE active) AS aktor_faol,
           count(*) FILTER (
               WHERE active AND rol IN ('koruvchi', 'tasdiqlovchi', 'admin')
           ) AS aktor_koruvchi
      FROM actor
     GROUP BY company_id
),
navbat AS (
    SELECT company_id, qatlam, navbatda, aktorli
      FROM v_inson_dalil
)
SELECT c.id AS company_id,
       n.qatlam,
       n.navbatda,
       n.aktorli,
       COALESCE(a.aktor_jami, 0)     AS aktor_jami,
       COALESCE(a.aktor_faol, 0)     AS aktor_faol,
       COALESCE(a.aktor_koruvchi, 0) AS aktor_koruvchi,
       -- TO'SIQ NIMA. Tartib muhim: eng erta to'sadigan sabab
       -- birinchi qaytadi, aks holda operator ikkinchi to'siqni
       -- tuzatib, birinchisiga qayta urilardi.
       CASE
           WHEN COALESCE(a.aktor_faol, 0) = 0
               THEN 'AKTOR YOQ — qarorlar anonim yoziladi'
           WHEN COALESCE(a.aktor_koruvchi, 0) = 0
               THEN 'KORUVCHI ROLI YOQ — faqat kuzatuvchi aktorlar'
           WHEN n.navbatda = 0
               THEN 'NAVBAT BOSH — korib chiqiladigan qator yoq'
           ELSE NULL
       END AS tosiq
  FROM company_account c
  JOIN navbat n     ON n.company_id = c.id
  LEFT JOIN aktorlar a ON a.company_id = c.id;

COMMENT ON VIEW v_pilot_tayyorlik IS
    'Pilot boshlanishidan OLDIN nima yetishmayotganini aytadi. '
    '`tosiq` NULL bo''lsa shu qatlamda aktorli qaror yozish mumkin.';

COMMIT;
