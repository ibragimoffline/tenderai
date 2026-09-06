-- =============================================================================
-- Sxema patch — HAQIQIY FAYL YUKLASH (kompaniya hujjatlari + AI chat)
-- Talab: schema_patch_compliance.sql (company_document)
-- Talab: schema_patch_ai_chat.sql (chat_session, vector kengaytmasi)
-- Talab: schema_patch_embed_384.sql (embedding o'lchami 384)
--
-- Ishga tushirish (idempotent):
--   psql "$XT_DB_DSN" -f schema_patch_yuklama.sql
--
-- =============================================================================
-- MUAMMO
-- =============================================================================
-- `company_document.file_ref` MATN edi va u "tashqi havola yoki yo'l" deb
-- hujjatlashtirilgan. Amalda 2026-09-06 da o'lchandi: 13 qatorning 13 tasi
-- ham shunday edi —
--
--     file:///D:/MVP%20projects/tender-ai/.runtime/company_documents/2/...
--
-- ya'ni BITTA ISHLAB CHIQUVCHI MASHINASINING mutlaq yo'li. Bu uch marta
-- buzilgan:
--   1. brauzer `http://` sahifadan `file://` ga o'tishni BLOKLAYDI —
--      havola bosiladi va HECH NARSA bo'lmaydi, xato ham chiqmaydi;
--   2. serverda bu yo'l umuman mavjud emas;
--   3. fizik fayl ASL NOM bilan yotardi (`ГАРАНТИЙНОЕ ПИСЬМО.docx`) —
--      ya'ni foydalanuvchi bergan nom fayl tizimi yo'liga aylanardi.
--
-- =============================================================================
-- YECHIM: `yuklama` — fayl HAQIDAGI yagona haqiqat
-- =============================================================================
-- Fizik fayl GENERATSIYA QILINGAN kalit bilan saqlanadi
-- (`<company_id>/<uuid>.<ext>`), asl nom esa FAQAT ko'rsatish uchun
-- ustunda qoladi. Ikkalasi bir joyda emas — bu ataylab.
--
-- NEGA ALOHIDA JADVAL, `company_document` ga ustun emas: ayni fayl
-- modeli AI chatga ham kerak va ikki joyda ikki xil model qurish
-- ikkita parser, ikkita tekshiruv va ikkita xavfsizlik yuzasi degani.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- 1. YUKLAMA — fayl yozuvi
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS yuklama (
    -- UUID, SERIAL EMAS. Ketma-ket son "keyingi id ni taxmin qilish"
    -- hujumini oson qiladi; bu yerda id saqlash kalitining bir qismi
    -- bo'lgani uchun taxmin qilinmasligi kerak. (Ruxsat baribir
    -- `company_id` bilan tekshiriladi — bu IKKINCHI qatlam.)
    id            UUID PRIMARY KEY,

    -- IJARACHI CHEGARASI. `NOT NULL` va FK: egasiz fayl bo'lishi
    -- MUMKIN EMAS, chunki "egasi noma'lum" holat ruxsat tekshiruvini
    -- ikki ma'noli qiladi.
    company_id    INTEGER NOT NULL
                  REFERENCES company_account(id) ON DELETE CASCADE,

    -- Fayl QAYERDAN kelgan. Ruxsat va qidiruv qamrovi shunga bog'liq,
    -- shuning uchun CHECK bilan qulflangan.
    manba_turi    TEXT NOT NULL
                  CHECK (manba_turi IN ('company_doc', 'chat')),

    -- FOYDALANUVCHI KO'RADIGAN NOM. Fayl tizimiga HECH QACHON
    -- bormaydi — `kalit` shuning uchun alohida.
    original_nom  TEXT NOT NULL,

    -- SAQLASH KALITI — `api/saqlash.py` yasaydi. Mutlaq yo'l EMAS:
    -- backend o'zgarsa (S3/MinIO) ayni kalit obyekt kaliti bo'ladi.
    -- Brauzerga HECH QACHON chiqmaydi.
    kalit         TEXT NOT NULL,

    -- `local` | `s3` | ... — qaysi backend saqlagan. Ko'chirishda
    -- qaysi qator ko'chirilganini bilish uchun.
    backend       TEXT NOT NULL DEFAULT 'local',

    mime          TEXT,
    ext           TEXT,
    size_bytes    BIGINT NOT NULL CHECK (size_bytes >= 0),

    -- BUTUNLIK va TAKRORNI ANIQLASH. Yuklab olingan fayl aynan
    -- yuklangani ekanini sinov shu bilan isbotlaydi.
    sha256        TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),

    -- HOLAT — `reja` emas, HAQIQIY holat.
    --
    -- `too_large` ATAYLAB YO'Q: chegara faylni saqlashdan OLDIN
    -- ishlaydi (`_yuklangani`), ya'ni bunday qator HECH QACHON
    -- yaratilmaydi. Yaratilmaydigan holatni ro'yxatga qo'shish —
    -- "holat bor" degan yolg'on beradi.
    holat         TEXT NOT NULL DEFAULT 'yuklandi'
                  CHECK (holat IN ('yuklandi',              -- saqlandi, navbatda
                                   'ajratilmoqda',          -- matn ajratilyapti
                                   'tayyor',                -- AI ISHLATA OLADI
                                   'qollab_quvvatlanmaydi', -- formatni parser bilmaydi
                                   'oqilmadi',              -- skan/chizma — OCR kerak
                                   'yiqildi')),             -- kutilmagan xato

    -- Foydalanuvchiga ko'rsatiladigan QISQA sabab. Stack trace,
    -- yo'l va DB xatosi BU YERGA TUSHMAYDI (§25).
    xato          TEXT,

    -- Ajratilgan matn uzunligi — "tayyor" da'vosini o'lchash uchun.
    -- 0 bo'lsa `tayyor` bo'la olmaydi (pastdagi CHECK).
    matn_belgi    INTEGER,
    sahifa_soni   INTEGER,
    -- Qaysi ajratgich ishlagan (`pypdf`, `python-docx`, ...).
    ajratgich     TEXT,

    uploaded_by   BIGINT REFERENCES actor(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    tayyor_at     TIMESTAMPTZ,

    -- ARXIV — O'CHIRISH EMAS. Hujjat muvofiqlik, malaka va o'tgan
    -- qarorlarda ishlatilgan bo'lishi mumkin; qatorni yo'q qilish
    -- o'sha qarorlarning DALILINI yo'q qiladi.
    arxiv_at      TIMESTAMPTZ,
    arxivladi     BIGINT REFERENCES actor(id) ON DELETE SET NULL,

    -- ALMASHTIRISH ZANJIRI: yangi yuklama eskisiga ishora qiladi.
    -- Eski qator QOLADI va uning iqtiboslari ishlayveradi (§22, §35).
    almashtirdi   UUID REFERENCES yuklama(id) ON DELETE SET NULL,

    -- "TAYYOR" YOLG'ON BO'LMASIN. `tayyor` faqat matn HAQIQATAN
    -- ajratilganda qo'yiladi. Aks holda UI "Ready" deb yozardi va
    -- AI fayldan hech narsa topa olmasdi (§17).
    CONSTRAINT yuklama_tayyor_matn_chk
        CHECK (holat <> 'tayyor' OR (matn_belgi IS NOT NULL AND matn_belgi > 0)),
    -- Xato holatida SABAB bo'lishi shart, aks holda foydalanuvchiga
    -- "nimadir bo'ldi" deb ko'rsatishdan boshqa iloj qolmaydi.
    CONSTRAINT yuklama_xato_sabab_chk
        CHECK (holat NOT IN ('qollab_quvvatlanmaydi', 'oqilmadi', 'yiqildi')
               OR xato IS NOT NULL)
);

-- Ro'yxat va kvota so'rovlari HAR DOIM kompaniya bo'yicha.
CREATE INDEX IF NOT EXISTS idx_yuklama_company
    ON yuklama(company_id, manba_turi, created_at DESC);
-- Navbatdagi ishni topish (`holat` bo'yicha).
CREATE INDEX IF NOT EXISTS idx_yuklama_holat
    ON yuklama(holat) WHERE holat IN ('yuklandi', 'ajratilmoqda');
-- Ayni fayl qayta yuklanganini aniqlash (kompaniya ichida).
CREATE INDEX IF NOT EXISTS idx_yuklama_sha
    ON yuklama(company_id, sha256);

COMMENT ON TABLE yuklama IS
    'Yuklangan fayl. Fizik fayl GENERATSIYA QILINGAN kalit bilan saqlanadi; '
    'asl nom faqat ko''rsatish uchun. Hard delete YO''Q — arxiv.';
COMMENT ON COLUMN yuklama.kalit IS
    'Saqlash kaliti (backend ichidagi). Brauzerga HECH QACHON chiqmaydi.';
COMMENT ON COLUMN yuklama.holat IS
    '`tayyor` = AI HAQIQATAN ishlata oladi (matn ajratilgan). `too_large` '
    'holati YO''Q: chegara saqlashdan oldin ishlaydi.';


-- ---------------------------------------------------------------------------
-- 2. YUKLAMA_CHUNK — bo'laklar va vektorlar
--
-- NEGA `doc_chunk` GA QO'SHILMADI. O'lchandi (2026-09-06):
--     doc_chunk.tender_id  BIGINT NOT NULL -> FK tender(id)
--     UNIQUE (tender_id, file_ref, chunk_no)
--     company_id ustuni YO'Q,  236 578 qator
-- Kompaniya faylini u yerga qo'yish uchun `tender_id` NULL bo'lishi
-- kerak edi — ya'ni 236 ming qatordagi cheklovni ZAIFLASHTIRISH.
-- Bundan tashqari `doc_chunk` OMMAVIY tender korpusi: kompaniya
-- hujjati u yerga tushsa, kompaniya chegarasi bo'lmagan har qanday
-- so'rov uni ko'rardi.
--
-- Shakl `doc_chunk` bilan ATAYLAB bir xil: ayni `chunk_text()` va
-- ayni embedder ishlatiladi, ikkinchi quvur qurilmaydi.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS yuklama_chunk (
    id            BIGSERIAL PRIMARY KEY,
    yuklama_id    UUID NOT NULL REFERENCES yuklama(id) ON DELETE CASCADE,

    -- IJARACHI TAKRORLANGAN. `yuklama` orqali JOIN qilib olish mumkin
    -- edi, lekin qidiruv so'rovida chegara BEVOSITA `WHERE` da
    -- turishi kerak: JOIN unutilsa korpus sizib chiqadi va buni
    -- hech narsa ushlamaydi.
    company_id    INTEGER NOT NULL
                  REFERENCES company_account(id) ON DELETE CASCADE,

    chunk_no      INTEGER NOT NULL,
    text          TEXT NOT NULL,
    char_start    INTEGER NOT NULL,
    char_end      INTEGER NOT NULL,
    -- Sahifa RAQAMI faqat PDF da MA'LUM. Boshqa formatда NULL
    -- qoladi va UI bo'lak raqamini ko'rsatadi — SOXTA sahifa
    -- raqami yasalmaydi (§20).
    sahifa        INTEGER,
    lang          CHAR(2),

    embedding     vector(384),
    embed_model   TEXT,
    embed_holat   TEXT CHECK (embed_holat IS NULL OR
                              embed_holat IN ('navbatda', 'ok', 'yiqildi')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (yuklama_id, chunk_no),
    CONSTRAINT yuklama_chunk_ok_vektor_chk
        CHECK (embed_holat <> 'ok' OR
               (embedding IS NOT NULL AND embed_model IS NOT NULL))
);

-- Leksik qidiruv — `doc_chunk` bilan bir xil yondashuv.
CREATE INDEX IF NOT EXISTS idx_yuklama_chunk_tsv
    ON yuklama_chunk USING gin (to_tsvector('simple', text));
-- Fayl bo'yicha o'qish (fayl-only savol).
CREATE INDEX IF NOT EXISTS idx_yuklama_chunk_fayl
    ON yuklama_chunk(yuklama_id, chunk_no);
-- Kompaniya bo'yicha semantik qidiruv.
--
-- HNSW ATAYLAB YO'Q. `doc_chunk` da o'lchangan (§16): korpus kichik
-- bo'lganda aniq (exact) qidiruv tezroq VA to'g'riroq. Bu jadval
-- kompaniya ichida kichik qoladi.
CREATE INDEX IF NOT EXISTS idx_yuklama_chunk_company
    ON yuklama_chunk(company_id);

COMMENT ON TABLE yuklama_chunk IS
    'Yuklangan fayl bo''laklari. `doc_chunk` dan ALOHIDA: u ommaviy tender '
    'korpusi, bu esa kompaniya chegarasi bilan yopiq.';


-- ---------------------------------------------------------------------------
-- 3. CHAT_YUKLAMA — fayl qaysi suhbatga biriktirilgan
--
-- M:N ATAYLAB: ayni fayl bir necha savolda ishlatilishi mumkin, va
-- kompaniya hujjati chatga biriktirilsa ham `yuklama` qatori BITTA
-- qoladi (ikkinchi nusxa yasalmaydi).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_yuklama (
    session_id   UUID NOT NULL REFERENCES chat_session(id) ON DELETE CASCADE,
    yuklama_id   UUID NOT NULL REFERENCES yuklama(id) ON DELETE CASCADE,

    -- IJARACHI UCHINCHI MARTA. `chat_session` ham, `yuklama` ham
    -- `company_id` ga ega — lekin BOG'LANISH ikkalasini kesib
    -- o'tadi va aynan shu yerda ular BOSHQA kompaniyaniki bo'lishi
    -- mumkin edi. Ustun + trigger bu holatni IMKONSIZ qiladi.
    company_id   INTEGER NOT NULL
                 REFERENCES company_account(id) ON DELETE CASCADE,

    -- UZILGAN (foydalanuvchi olib tashladi), lekin O'CHIRILMAGAN.
    -- Javob allaqachon shu faylga tayangan bo'lsa, iqtibos
    -- ishlayverishi kerak (§22).
    uzildi_at    TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (session_id, yuklama_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_yuklama_sessiya
    ON chat_yuklama(session_id) WHERE uzildi_at IS NULL;

-- IJARACHI BUZILISHINI BAZA O'ZI RAD ETADI.
--
-- NEGA TRIGGER, IZOH EMAS: "endpoint tekshiradi" degan va'da bitta
-- unutilgan `WHERE` bilan buziladi va buni hech narsa ko'rmaydi.
-- Bu yerda buzilish INSERT paytida to'xtaydi.
CREATE OR REPLACE FUNCTION chat_yuklama_ijarachi_tekshir()
RETURNS TRIGGER AS $$
DECLARE
    s_company INTEGER;
    y_company INTEGER;
BEGIN
    SELECT company_id INTO s_company FROM chat_session WHERE id = NEW.session_id;
    SELECT company_id INTO y_company FROM yuklama      WHERE id = NEW.yuklama_id;
    IF s_company IS DISTINCT FROM NEW.company_id
       OR y_company IS DISTINCT FROM NEW.company_id THEN
        RAISE EXCEPTION
            'chat_yuklama: ijarachi mos emas (sessiya=%, yuklama=%, qator=%)',
            s_company, y_company, NEW.company_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_chat_yuklama_ijarachi ON chat_yuklama;
CREATE TRIGGER trg_chat_yuklama_ijarachi
    BEFORE INSERT OR UPDATE ON chat_yuklama
    FOR EACH ROW EXECUTE FUNCTION chat_yuklama_ijarachi_tekshir();


-- ---------------------------------------------------------------------------
-- 4. COMPANY_DOCUMENT -> YUKLAMA
--
-- `file_ref` OLIB TASHLANMAYDI. Mavjud 13 qatorda u to'ldirilgan va
-- ularni bir vaqtning o'zida ko'chirib bo'lmaydi (fayllar faqat
-- ishlab chiquvchi mashinasida). `NOT NULL` ham QO'YILMAYDI —
-- eski qatorlarda `yuklama_id` bo'sh (§29: cheklov qo'yishdan oldin
-- mavjud qatorlar KELISHTIRILISHI kerak, bu esa alohida ish).
-- ---------------------------------------------------------------------------
ALTER TABLE company_document
    ADD COLUMN IF NOT EXISTS yuklama_id UUID
        REFERENCES yuklama(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_company_document_yuklama
    ON company_document(yuklama_id);

COMMENT ON COLUMN company_document.yuklama_id IS
    'Yuklangan haqiqiy fayl. NULL = eski qator (`file_ref` matn havolasi). '
    '`file_ref` MIGRATSIYA UCHUN qoldirildi, yangi qatorlarda ishlatilmaydi.';


-- ---------------------------------------------------------------------------
-- 5. KO'RINISH — chat uchun tayyor fayllar
--
-- Endpointlar va sinovlar AYNI ta'rifni ishlatsin: "tayyor" ning
-- ma'nosi ikki joyda ikki xil bo'lib qolmasin.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_chat_fayl AS
SELECT cy.session_id,
       cy.company_id,
       y.id            AS yuklama_id,
       y.original_nom,
       y.mime,
       y.ext,
       y.size_bytes,
       y.holat,
       y.xato,
       y.matn_belgi,
       y.sahifa_soni,
       cy.uzildi_at,
       y.created_at,
       (SELECT count(*) FROM yuklama_chunk c WHERE c.yuklama_id = y.id)
                       AS chunk_soni
  FROM chat_yuklama cy
  JOIN yuklama y ON y.id = cy.yuklama_id
 WHERE y.arxiv_at IS NULL;

COMMENT ON VIEW v_chat_fayl IS
    'Suhbatga biriktirilgan fayllar. `uzildi_at` NULL bo''lmasa fayl '
    'foydalanuvchi tomonidan olib tashlangan, lekin DALIL sifatida qoladi.';
