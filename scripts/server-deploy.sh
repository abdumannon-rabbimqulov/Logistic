#!/usr/bin/env bash
# Serverda deploy / yangilash. Idempotent — xohlagancha qayta ishga tushirish mumkin.
#
#   ./scripts/server-deploy.sh          — git pull + build + up
#   ./scripts/server-deploy.sh --no-pull  — kodni tortmasdan (lokal sinov uchun)
#
# Nomi ataylab `deploy.sh` EMAS: `.gitignore` da `deploy.sh` qatori bor va u
# (slashsiz naqsh bo'lgani uchun) istalgan papkadagi shu nomli faylni yashiradi.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[0;33m'; NC='\033[0m'
say()  { printf "${GRN}==>${NC} %s\n" "$*"; }
warn() { printf "${YLW}!!${NC}  %s\n" "$*"; }
die()  { printf "${RED}XATO:${NC} %s\n" "$*" >&2; exit 1; }

PULL=1
[ "${1:-}" = "--no-pull" ] && PULL=0

# ── 1. Old shartlar ─────────────────────────────────────────────────────────
command -v docker >/dev/null || die "docker o'rnatilmagan. docs/DEPLOY.md ga qarang."
docker compose version >/dev/null 2>&1 || die "'docker compose' (v2) topilmadi."

[ -f "$ROOT/.env" ] || die ".env fayli yo'q. Namuna: cp .env.example .env && nano .env"

# .env dagi majburiy o'zgaruvchilar. Qiymatlar EKRANGA CHIQARILMAYDI — faqat
# bo'sh yoki namunaviy qoldirilganlari aytiladi.
missing=()
placeholder=()
check_env() {
    local name="$1"
    local value
    # `.env` ni source qilmaymiz: ichida tirnoqsiz maxsus belgilar bo'lishi mumkin.
    value="$(grep -E "^${name}=" "$ROOT/.env" | tail -n1 | cut -d= -f2- || true)"
    if [ -z "$value" ]; then
        missing+=("$name")
    elif printf '%s' "$value" | grep -qiE 'change_me|your_|example\.(org|uz|com)'; then
        placeholder+=("$name")
    fi
}
for v in BOT_TOKEN SECRET_KEY DB_PASSWORD DB_URL DOMAIN WEBAPP_URL; do check_env "$v"; done

[ ${#missing[@]} -eq 0 ] || die ".env da to'ldirilmagan: ${missing[*]}"
if [ ${#placeholder[@]} -gt 0 ]; then
    die ".env da hali namunaviy qiymat turibdi: ${placeholder[*]} — haqiqiysiga almashtiring."
fi

# WEBAPP_URL https bo'lmasa Telegram Mini App menyu tugmasi umuman qo'yilmaydi
# (main.py `_setup_menu_button`). Bu jimgina o'tib ketadigan xato, shuning uchun
# deploy'ni to'xtatamiz.
webapp_url="$(grep -E '^WEBAPP_URL=' "$ROOT/.env" | tail -n1 | cut -d= -f2-)"
case "$webapp_url" in
    https://*) ;;
    *) die "WEBAPP_URL https:// bilan boshlanishi shart (hozir: $webapp_url)" ;;
esac

# ── 2. OSRM xaritasi ────────────────────────────────────────────────────────
# ~1 GB, git'da saqlanmaydi. Busiz `osrm` konteyneri healthcheck'dan o'tmaydi va
# web/bot/dispatch-worker (`service_healthy` kutadi) umuman ishga tushmaydi.
if [ ! -f "$ROOT/osrm-data/uzbekistan.osrm" ]; then
    die "osrm-data/uzbekistan.osrm topilmadi. Avval xaritani tayyorlang:
    ./scripts/update-osrm-map.sh
  (~1 GB yuklab olinadi va qayta ishlanadi — birinchi marta uzoq davom etadi)"
fi

# ── 3. Kodni yangilash ──────────────────────────────────────────────────────
if [ "$PULL" = "1" ] && [ -d "$ROOT/.git" ]; then
    say "Kod yangilanmoqda (git pull)..."
    SELF="$ROOT/scripts/server-deploy.sh"
    before="$(git hash-object "$SELF")"
    git pull --ff-only
    # Pull shu skriptning o'zini o'zgartirgan bo'lsa — bash hali ESKI nusxani bajarmoqda
    # (ochiq fayl). Yangi versiya bilan qaytadan boshlanadi, aks holda yangi qadamlar
    # (masalan oxiridagi commit qatori, Actions shuni tekshiradi) bajarilmay qoladi.
    if [ "$(git hash-object "$SELF")" != "$before" ]; then
        say "Deploy skripti yangilandi — yangi versiyasi bilan qayta ishga tushirilmoqda..."
        exec "$SELF" --no-pull
    fi
fi

# Image'lar GitHub Actions'da yig'ilib GHCR'ga yuklanadi (`.github/workflows/deploy.yml`,
# `build` job). Teg — aynan shu commit SHA, shuning uchun server kod bilan bir xil
# image'ni oladi.
export IMAGE_TAG="$(git rev-parse HEAD)"
BACKEND_IMAGE="ghcr.io/abdumannon-rabbimqulov/logistika-backend"
PREV_IMAGE="$("${COMPOSE[@]}" images -q web 2>/dev/null | head -n1 || true)"
[ -n "$PREV_IMAGE" ] || PREV_IMAGE="-"

# ── 4. Image'larni olish (build EMAS) va ishga tushirish ────────────────────
say "Image'lar GHCR'dan olinmoqda (teg ${IMAGE_TAG:0:7})..."
if ! "${COMPOSE[@]}" pull --quiet; then
    # Zaxira: registry ishlamasa yoki image hali yuklanmagan bo'lsa — serverda build,
    # lekin ATAYLAB BITTADAN: parallel build 2 vCPU / 3.8 GB serverni xotirasiz
    # qotirgan (2026-11-19 deploy'i, SSH ham javob bermagan).
    warn "Registry'dan olib bo'lmadi — serverda ketma-ket build qilinadi (sekin)."
    for svc in $("${COMPOSE[@]}" config --services); do
        "${COMPOSE[@]}" build "$svc"
    done
fi

# Mikroservislarning alohida bazalari (support_db, chat_db). Postgres init skriptlari
# FAQAT bo'sh ma'lumot katalogida ishlaydi — mavjud prod bazasida yangi servis
# (masalan chat) bazasi o'zi paydo bo'lmaydi. Skriptlar idempotent (WHERE NOT EXISTS),
# shuning uchun har deploy'da xavfsiz qayta ishga tushiriladi.
say "Servis bazalari tekshirilmoqda (support_db, chat_db)..."
"${COMPOSE[@]}" up -d --no-build db
for _ in $(seq 1 30); do
    [ "$("${COMPOSE[@]}" ps --format '{{.Health}}' db 2>/dev/null)" = "healthy" ] && break
    sleep 2
done
for init in 10-support-db.sh 11-chat-db.sh; do
    "${COMPOSE[@]}" exec -T db bash "/docker-entrypoint-initdb.d/$init" \
        || warn "$init bajarilmadi — bazani qo'lda yarating (skript izohiga qarang)"
done

say "Xizmatlar ishga tushirilmoqda..."
# `--remove-orphans` — eski nomdagi konteynerlar (masalan avvalgi prod nomlari)
# qolib ketmasin.
"${COMPOSE[@]}" up -d --no-build --remove-orphans

# ── 5. Sog'liqni kutish ─────────────────────────────────────────────────────
say "Xizmatlar tayyor bo'lishi kutilmoqda..."
deadline=$(( $(date +%s) + 300 ))
while :; do
    unhealthy="$("${COMPOSE[@]}" ps --format '{{.Service}} {{.State}} {{.Health}}' 2>/dev/null \
        | awk '$3 != "" && $3 != "healthy" { print $1 }' || true)"
    stopped="$("${COMPOSE[@]}" ps --format '{{.Service}} {{.State}}' 2>/dev/null \
        | awk '$2 != "running" && $1 != "migrate" { print $1 }' || true)"
    if [ -z "$unhealthy" ] && [ -z "$stopped" ]; then
        break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        warn "5 daqiqada hamma xizmat tayyor bo'lmadi. Holat:"
        "${COMPOSE[@]}" ps
        warn "Loglar:  docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=50"
        exit 1
    fi
    sleep 5
done

# ── 6. Tekshiruv ────────────────────────────────────────────────────────────
say "Backend /health tekshirilmoqda..."
"${COMPOSE[@]}" exec -T web curl -fsS http://127.0.0.1:8000/health >/dev/null \
    && say "Backend javob bermoqda." \
    || die "Backend /health javob bermadi."

domain="$(grep -E '^DOMAIN=' "$ROOT/.env" | tail -n1 | cut -d= -f2-)"
say "Tayyor: https://${domain}"
# GitHub Actions shu qatorni push qilingan commit bilan solishtiradi
# (.github/workflows/deploy.yml) — formatini o'zgartirmang.
echo "Deploy qilingan commit: $(git rev-parse HEAD)"

# ── 7. Tozalash ─────────────────────────────────────────────────────────────
# Faqat hech qaysi konteyner ishlatmayotgan "osilib qolgan" qatlamlar.
docker image prune -f >/dev/null 2>&1 || true
# Har deploy yangi SHA teg olib keladi — 7 kundan eski, ishlatilmayotgan image'lar o'chiriladi.
docker image prune -af --filter "until=168h" >/dev/null 2>&1 || true

if [ "$PREV_IMAGE" != "-" ]; then
    echo
    warn "Rollback kerak bo'lsa — oldingi commit bilan:"
    warn "  git checkout <oldingi_commit> && IMAGE_TAG=<oldingi_commit> \\"
    warn "  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-build"
    warn "(oldingi backend image id: ${PREV_IMAGE:0:12}, repo: ${BACKEND_IMAGE})"
fi
