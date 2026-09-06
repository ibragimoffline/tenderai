-- =============================================================================
-- Sxema patch — ERP GA TOPSHIRIQ (yo'naltirish oqimi, HTTP'siz)
-- Ishga tushirish (idempotent, bir necha marta ishlatsa ham xavfsiz):
--   psql "dbname=xtxarid user=postgres host=localhost" -f schema_patch_topshiriq.sql
-- Talab: tender_routing (schema_patch_routing.sql), actor (schema_patch_aktor.sql).
--
-- Shartnoma: ERP repozitoriysidagi `erp_rollar.md` §5.
--
-- MUAMMO: broker navbatda "Olindi" deydi va shu yerda zanjir UZILADI.
-- ERP kartani QO'LDA ochishga majbur: tenderni qidiradi, mijozni
-- tanlaydi, muddatni ko'chiradi. Ya'ni qaror BU YERDA, ish esa U
-- YERDA va ikkalasi orasida odam turadi.
--
-- NEGA HTTP EMAS: ikkala tomon ham tarmoqqa chiqmaydi degan qoida
-- (`docs/erp_kimlik.md`, ERP `erp_arxitektura_2.md`). Baza esa
-- BITTA — demak eng arzon va eng ishonchli yo'l: har tomon O'Z
-- jadvaliga yozadi, qarshi tomon VIEW dan o'qiydi.
--
--     Tender-AI  ->  tender_topshiriq  ->  v_erp_topshiriq  ->  ERP
--     ERP        ->  erp.opportunity   ->  erp.v_tender_status -> Tender-AI
--
-- Chegara buzilmaydi: Tender-AI `erp.*` ga YOZMAYDI, ERP `public.*`
-- ga YOZMAYDI. Ikkala loyihaning sinovi buni tekshiradi.
--
-- NEGA ALOHIDA JADVAL, `tender_routing` GA USTUN EMAS:
--   1. `tender_routing` — QAROR yozuvi (AI va inson). Unga "kimga
--      berildi, qanday muddat bilan" qo'shish ikki tushunchani
--      aralashtirardi.
--   2. Topshiriq QAYTA berilishi mumkin (tahlil yangilanishi).
--      Qaror esa bitta.
--   3. ERP ga ochiladigan yuza TOR bo'lishi kerak: `tender_routing`
--      da AI ning ichki maydonlari bor va ular ERP ga kerak emas.
--
-- TAHLIL — SNAPSHOT: `tahlil` JSONB qaror paytida hisoblanadi va
-- keyin O'ZGARMAYDI. ERP uni qayta hisoblamaydi. Sabab loyihada
-- takrorlanadi (faktura rekvizitlari, karta snapshoti): hujjat
-- chiqarilgandan keyin manba o'zgarsa, hujjat o'zgarmasligi kerak.
-- =============================================================================

CREATE TABLE IF NOT EXISTS tender_topshiriq (
    id             SERIAL PRIMARY KEY,
    company_id     INT    NOT NULL,
    --: Qaysi qarordan tug'ilgan. `tender_routing` o'chirilmaydi.
    routing_id     INT    NOT NULL REFERENCES tender_routing(id),
    tender_id      BIGINT NOT NULL,
    --: KIMGA berildi (ERP hodimiga xaritalangan aktor). NULL —
    --: "Taqsimlanmagan": ERP kartani baribir ochadi va menejerga
    --: bildirishnoma yuboradi. Jimgina yo'qolmaydi.
    hodim_actor_id INT,
    --: KIM berdi.
    yonaltirgan_actor_id INT,
    --: `audit_jurnal.ishonch` bilan BIR XIL lug'at: erp_sessiya /
    --: aktor_elon / kompaniya_sessiyasi / servis. ERP yorliqni
    --: DALILDAN OSHIRMAYDI ("e'lon qilingan" deb ko'rsatadi).
    ishonch        TEXT   NOT NULL,
    ustuvorlik     TEXT   NOT NULL DEFAULT 'medium'
                   CHECK (ustuvorlik IN ('low', 'medium', 'high')),
    izoh           TEXT,
    muddat         DATE,
    --: TAHLIL SNAPSHOTI (erp_rollar.md §6). Qaror paytidagi holat.
    tahlil         JSONB  NOT NULL DEFAULT '{}'::jsonb,
    yaratilgan_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    --: Qaror bekor qilinganda (`olindi` -> `rad`) belgilanadi. Yozuv
    --: O'CHIRILMAYDI: ERP kartasi ham o'chmaydi, `rejected` ga
    --: o'tadi va tarixda sabab qoladi.
    bekor_at       TIMESTAMPTZ,
    --: IJARACHI IZOLYATSIYASI — kompozit FK (docs/erp_kimlik.md §5).
    --: Boshqa ijarachining aktorini bu yerga yozib bo'lmaydi.
    FOREIGN KEY (company_id, hodim_actor_id)       REFERENCES actor (company_id, id),
    FOREIGN KEY (company_id, yonaltirgan_actor_id) REFERENCES actor (company_id, id),
    --: Bitta qarordan bitta topshiriq. ERP ham `routing_id` ni
    --: UNIQUE qiladi — takror karta ochilmasin.
    UNIQUE (routing_id)
);

COMMENT ON TABLE tender_topshiriq IS
    'ERP ga yo''naltirish topshirig''i (erp_rollar.md §5). Tender-AI '
    'yozadi, ERP v_erp_topshiriq orqali O''QIYDI. tahlil - SNAPSHOT, '
    'qayta hisoblanmaydi.';

CREATE INDEX IF NOT EXISTS tender_topshiriq_yangi_idx
    ON tender_topshiriq (yaratilgan_at DESC);
CREATE INDEX IF NOT EXISTS tender_topshiriq_tender_idx
    ON tender_topshiriq (company_id, tender_id);

-- --------------------------------------------------------------------------
-- SHARTNOMA-VIEW — ERP faqat shuni ko'radi
-- --------------------------------------------------------------------------
-- Aktor id lari ERP uchun MA'NOSIZ (ular Tender-AI ning ichki
-- raqamlari), shuning uchun view ularni `erp_user_id` ga aylantiradi.
-- Ism ham beriladi: ERP tarixga "kim -> kimga" deb yozadi va buning
-- uchun ikkinchi so'rov qilishi shart emas.
CREATE OR REPLACE VIEW v_erp_topshiriq AS
SELECT t.id,
       t.company_id,
       t.routing_id,
       t.tender_id,
       ah.erp_user_id AS hodim_app_user_id,
       ah.ism         AS hodim_ism,
       ay.erp_user_id AS yonaltirgan_app_user_id,
       ay.ism         AS yonaltirgan_ism,
       t.ishonch,
       t.ustuvorlik,
       t.izoh,
       t.muddat,
       t.tahlil,
       t.yaratilgan_at,
       t.bekor_at
FROM tender_topshiriq t
LEFT JOIN actor ah ON ah.company_id = t.company_id AND ah.id = t.hodim_actor_id
LEFT JOIN actor ay ON ay.company_id = t.company_id AND ay.id = t.yonaltirgan_actor_id;

COMMENT ON VIEW v_erp_topshiriq IS
    'SHARTNOMA: ERP shu view ni o''qiydi (faqat o''qish). Ustunlarni '
    'o''zgartirish ERP ni buzadi (u yerda api/erp/topshiriq.py). '
    'Yangi ustun faqat OXIRIGA qo''shiladi.';

-- --------------------------------------------------------------------------
-- XABAR — ERP kutib turmasin
-- --------------------------------------------------------------------------
-- NEGA TRIGGER, ILOVA KODI EMAS: `doc_audit` bilan bir xil sabab.
-- Qatorni qo'lda `psql` dan qo'ygan odam ham xabar yuborilishini
-- kutadi; ilova qatlamidagi `pg_notify` esa faqat o'z yo'lini
-- biladi.
--
-- YUK YENGIL: faqat `id`. ERP xabarni olib, view dan O'QIYDI —
-- ma'lumotni xabar ichida tashish uni ikki joyda saqlash bo'lardi
-- (va `pg_notify` ning 8000 baytlik chegarasi bor).
--
-- ERP TINGLAMASA HAM YO'QOLMAYDI: u ishga tushganda "oxirgi
-- ko'rilgandan keyingi" topshiriqlarni view dan o'qib oladi.
-- `NOTIFY` — tezlik uchun, ishonchlilik uchun emas.
CREATE OR REPLACE FUNCTION erp_topshiriq_xabar() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('erp_topshiriq', COALESCE(NEW.id, OLD.id)::text);
    RETURN NULL;                       -- AFTER trigger, natija kerak emas
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS erp_topshiriq_xabar_trg ON tender_topshiriq;
CREATE TRIGGER erp_topshiriq_xabar_trg
    AFTER INSERT OR UPDATE ON tender_topshiriq
    FOR EACH ROW EXECUTE FUNCTION erp_topshiriq_xabar();

-- --------------------------------------------------------------------------
-- HUQUQ — ERP roli faqat shu view ni ko'radi
-- --------------------------------------------------------------------------
-- Rol bo'lmasa patch yiqilmaydi (ERP hozir `postgres` bilan ulanadi;
-- rol ajratilganda shu grant kuchga kiradi).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp') THEN
        GRANT USAGE ON SCHEMA public TO erp;
        GRANT SELECT ON v_erp_topshiriq TO erp;
    ELSE
        RAISE NOTICE 'erp roli yo''q - GRANT o''tkazib yuborildi.';
    END IF;
END $$;
