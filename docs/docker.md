# Docker — bosqichma-bosqich joriy etish

**Sana:** 2026-09-08 · **Holat:** Faza 1 (darvoza) qurildi va qisman
paritetdan o'tdi. Faza 2 (staging) **boshlanmagan**.

Docker bu yerda **qo'shimcha**, almashtirish emas. Host joylashtirishi,
systemd, nginx, `venv` va `tender-darvoza` o'zgarmadi.

---

## 1. Nega — o'lchangan sabablar

Docker "yaxshi amaliyot" bo'lgani uchun emas, **uch marta yolg'on natija
bergani** uchun kiritildi:

| nuqson | oqibat |
|---|---|
| `run_tests.py` bolani `sys.executable` bilan yurgizardi, u venv ga yechilmasdi | 5 to'plam "dotenv yo'q" deb yiqilardi |
| `pricing_test` PATH dagi birinchi `node` ni olardi | natija mashinaga qarab o'zgarardi |
| `requirements-api.txt` da **bitta ham `==` yo'q** | har o'rnatish boshqa versiyalarni yechishi mumkin |

**Diqqat:** OS portativligi bu ro'yxatda YO'Q. Audit ko'rsatdi:
`os.name`/`sys.platform` faqat uch **sinov** faylida, mahsulot kodida
qotirilgan `/tmp`, `/opt/tenderai` yoki `C:\` yo'q. Docker ning foydasi
bu loyihada **bog'liqlik va ijrochi determinizmi**.

## 2. Arxitektura

```
Faza 1 (BAJARILDI)          Faza 2 (REJA)              Faza 3 (KEYIN)

nomzod SHA                  Internet                   production
   |                           |                       (ayni DIGEST,
   v                        HOST nginx                  qayta qurilmaydi)
Docker gate imiji              |
   |                        Docker backend
izolyatsiyalangan baza         |
(HOSTDA)                    HOST PostgreSQL
   |
44 to'plam
```

nginx ham, PostgreSQL ham **hostda qoladi**. Zaxira strategiyasi,
sertifikatlar va baza hayot sikli tegilmaydi.

## 3. Imijlar

| fayl | maqsad | hajm |
|---|---|---|
| `Dockerfile.gate` | darvoza (sinovlar, `git`, `psql`) | **2.48 GB** |
| `Dockerfile.backend` | ilova ijrosi | **2.13 GB** |

Hajm asosan `torch==2.14.0+cpu` (~1.5 GB). U qulfda bor, chunki qulf
ishlab turgan relizdan olingan va u `EMBED_INSTALL=1` bilan qurilgan
(`EMBED_PROVIDER=local` uchun torch shart). Embeddingsiz nusxa kerak
bo'lsa alohida qulf yasaladi.

Qurilish konteksti: **10.3 MB** (`node_modules` 315 MB va `.venv`
1.5 GB `.dockerignore` bilan chiqarilgan).

## 4. Buyruqlar

```bash
# Qurish
docker build -f Dockerfile.gate    -t tenderai-gate:<SHA>    .
docker build -f Dockerfile.backend -t tenderai-backend:<SHA> .

# Bitta to'plam (bazasiz)
docker run --rm --network none tenderai-gate:<SHA> --only pricing_test

# To'liq darvoza (baza kerak — quyidagi to'siqqa qarang)
GATE_DSN="dbname=<gate> user=tai_service ..." \
  docker compose -f docker-compose.gate.yml run --rm darvoza
```

## 5. O'lchangan paritet

Ayni SHA da, host darvozasi va Docker:

| to'plam | host | Docker | izoh |
|---|---|---|---|
| `deploy_test` | 337/337 | **337/337** | ayni |
| `pricing_test` | 25/26 | **26/26** | Docker to'g'ri |

`pricing_test` farqi **tasodifiy emas**: rasmiy `node` imiji `amaro`
bilan quriladi, Debian paketi yo'q. Konteynerda `.ts` importi ishlaydi,
hostda `ERR_NO_TYPESCRIPT`.

`deploy_test` 337 (340 emas) — imijda `.git` yo'q, bajarish-bayrog'i
sinovi fayl-tizimi zaxira yo'liga tushadi. **Host darvozasi ham 337
beradi** (u ham `.toliq` da). 340 faqat ishchi nusxada.

## 6. TO'LIQ 44 TO'PLAM — ikki to'siq

Bu Faza 1 ning yakunlanmagan qismi va Faza 2 dan **oldin** yopilishi kerak.

**a) `tenderai` docker guruhida emas.** Darvoza o'ramasi `tenderai`
nomidan yuradi, konteyner esa `ibragimoff` huquqini talab qiladi.

> Uni docker guruhiga qo'shish **TAVSIYA QILINMAYDI**: docker soketi
> root-ekvivalenti va bu xizmat hisobiga root berish demak — butun
> loyiha qurgan eng kam imtiyoz chizig'ini buzadi.

Yechim: `tender-darvoza` kabi **cheklangan o'rama**, u muhit faylini
root sifatida o'qiydi va `docker run` ni chaqiradi; konteyner esa
root emas (uid 10001).

Mantiq repozitoriyada tayyor: `deploy/bin/darvoza-docker.sh` (nom
qo'riqchasi, rol tekshiruvi, kesh ulash, `cap-drop ALL`). O'ramaning
o'zi shundan iborat:

```bash
#!/usr/bin/env bash
# /usr/local/sbin/tender-darvoza-docker
set -euo pipefail
ENV_FILE=/etc/tenderai/staging.env
REPO=/opt/tenderai/repo.git
[ "$(id -u)" = 0 ] || { echo "root kerak"; exit 1; }

set -a; . "$ENV_FILE"; set +a          # sir root sifatida o'qiladi

SHA="$(sudo -u tenderai git --git-dir="$REPO" rev-parse 'main^{commit}')"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "SHA aniqlanmadi"; exit 1; }

VAQT="$(mktemp -d)"; trap 'rm -rf "$VAQT"' EXIT
sudo -u tenderai git --git-dir="$REPO" archive "$SHA" | tar -x -C "$VAQT"
echo "darvoza SHA: $SHA" >&2

# Imij AYNI SHA dan quriladi (kesh bo'lsa tez).
docker build -q -f "$VAQT/Dockerfile.gate" -t "tenderai-gate:$SHA" "$VAQT" >&2

IMIJ="tenderai-gate:$SHA" exec "$VAQT/deploy/bin/darvoza-docker.sh" "$@"
```

O'rnatish:

```bash
sudo install -m 0755 /dev/stdin /usr/local/sbin/tender-darvoza-docker <<'SH'
...yuqoridagi matn...
SH
echo 'ibragimoff ALL=(root) NOPASSWD: /usr/local/sbin/tender-darvoza-docker' \
  | sudo tee /etc/sudoers.d/tender-darvoza-docker
```

**Nima berilmaydi:** `tenderai` docker guruhiga QO'SHILMAYDI va
konteynerga docker soketi ULANMAYDI. O'rama root sifatida ishlaydi,
lekin faqat bitta narsani qiladi — imijni qurib, konteynerni
ko'taradi.

**b) PostgreSQL faqat `127.0.0.1` da tinglaydi** va docker
ko'prigidan ko'rinmaydi. `network_mode: host` tanlandi: u yangi hech
narsa ochmaydi, konteyner shunchaki o'sha loopback ni ko'radi.
Bazani `172.17.0.1` ga ochish **rad etildi** — u kengroq yuza.

## 7. Model keshi

Kesh (**471 MB**) imijga **bokilmaydi**: u reviziyaga bog'liq va har
build ni og'irlashtirardi. U `:ro` ulanadi, darvoza esa
`HF_HUB_OFFLINE=1` bilan yuradi — tarmoq so'rovlari **0** (o'lchandi).

## 8. Faza 2 — staging ko'chirish rejasi

Faqat to'liq 44 to'plam pariteti isbotlangach:

1. `tenderai-backend:<SHA>` qurish (ayni nomzod SHA)
2. Konteynerni **boshqa portda** ko'tarish (masalan 8012)
3. `/health` va `/ready` ni tekshirish — nginx **hali tegilmaydi**
4. Auth, AI Chat, fayl yuklash, ETL ni sinash
5. nginx upstream ni 8011 -> 8012 ga o'tkazish
6. Kuzatish; muammo bo'lsa quyidagi qaytarish

Baza, nginx, sertifikat, zaxira — **hech biri o'zgarmaydi**.

## 9. Qaytarish (Faza 2 uchun)

Baza qaytarish **KERAK EMAS**: faqat ijro qadoqlash o'zgardi, sxema
emas.

```bash
sudo docker stop tenderai-staging          # 1. konteyner to'xtaydi
sudo /usr/local/sbin/tender-nginx          # 2. upstream 8011 ga qaytadi
sudo systemctl start tenderai-api@staging  # 3. eski systemd relizi
curl -sS 127.0.0.1:8011/health             # 4. tiriklik
curl -sS 127.0.0.1:8011/ready              # 5. tayyorlik
```

## 10. Xavfsizlik

| talab | holat |
|---|---|
| root emas | uid 10001 (gate) / 10002 (backend) |
| docker soketi ulanmaydi | ha |
| privileged emas | ha |
| sir imij qatlamida | **yo'q** — ish vaqtida `env_file` dan |
| muhit fayli egaligi | root, o'zgarmadi |
| `cap_drop: ALL` | ha (compose) |
| `no-new-privileges` | ha |
| host tarmoq | faqat darvoza, asoslangan (6b) |

## 11. Doimiy ma'lumot konteynerda EMAS

PostgreSQL, yuklamalar, zaxiralar, model keshi va jurnallar —
hammasi konteyner qatlamidan tashqarida. Konteyner o'chirilsa hech
narsa yo'qolmaydi.
