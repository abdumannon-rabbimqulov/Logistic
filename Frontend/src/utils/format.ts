import { orderStatusMeta } from './orderStatus';

export function formatPrice(value: number): string {
  return Math.round(value).toLocaleString('uz-UZ').replace(/,/g, ' ');
}

export function formatEta(minutesFromNow: number): string {
  const eta = new Date(Date.now() + minutesFromNow * 60_000);
  return eta.toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit', hour12: false });
}

export function formatRelativeDate(iso: string): string {
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const diffDays = Math.floor(diffMs / (24 * 60 * 60 * 1000));
  if (diffDays <= 0) return 'Bugun';
  if (diffDays === 1) return 'Kecha';
  if (diffDays < 7) return `${diffDays} kun oldin`;
  const weeks = Math.floor(diffDays / 7);
  if (weeks === 1) return "1 hafta oldin";
  if (weeks < 5) return `${weeks} hafta oldin`;
  return date.toLocaleDateString('uz-UZ');
}

export function routeLabel(originAddress: string | null | undefined, destinationAddress: string | null | undefined): string {
  return `${shortAddress(originAddress) || '?'} → ${shortAddress(destinationAddress) || '?'}`;
}

/** Neytral qisqa status yorlig'i (haydovchi/admin). Mijoz ekranlari
 *  `orderStatusMeta(status).label` ni ishlatadi. Manba — `utils/orderStatus.ts`. */
export function statusLabel(status: string): string {
  return orderStatusMeta(status).short;
}

/** Manzilda yukni tushirish sharti (order/models.py `UnloadingMode`) — mijoz ham,
 *  haydovchi ham bir xil matnni ko'rishi uchun shu yerda. Shart tanlanmagan bo'lsa
 *  `null` qaytadi va chaqiruvchi qatorni umuman ko'rsatmaydi. */
export function unloadingLabel(
  mode: string | null | undefined,
  waitHours?: number | null,
): string | null {
  switch (mode) {
    case 'IMMEDIATE':
      return "O'sha zahoti tushirish";
    case 'HOURS':
      return waitHours ? `${waitHours} soat kutish` : 'Bir necha soat kutish';
    case 'DAY':
      return 'Kun kutish';
    default:
      return null;
  }
}

// Loyiha faqat O'zbekiston ichida — manzildagi davlat nomi ortiqcha.
// Faqat vergul bilan ajratilgan alohida bo'lak olib tashlanadi: "Oʻzbekiston ko'chasi"
// kabi ko'cha nomlariga tegilmaydi.
const COUNTRY =
  "(?:o['‘’ʻʼ`]?zbekiston|uzbekistan|узбекистан|ўзбекистон)(?:\\s+(?:respublikasi|республикаси|республика))?";
const COUNTRY_PREFIX = new RegExp(`^\\s*${COUNTRY}\\s*(?:,\\s*|$)`, 'i');
const COUNTRY_SUFFIX = new RegExp(`\\s*,\\s*${COUNTRY}\\s*$`, 'i');

export function shortAddress(address: string | null | undefined): string {
  if (!address) return '';
  return address.replace(COUNTRY_PREFIX, '').replace(COUNTRY_SUFFIX, '').trim();
}

// ── Sana/vaqt va pul formatlari ────────────────────────────────────────────
// Ilgari har sahifada o'z `formatDateTime`/`formatTime`/`formatMoney` nusxasi bor edi
// (10+ joy) — bir xil sana turli ekranlarda turlicha ko'rinardi.

function toDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** To'liq sana va vaqt (admin jadvallari). Bo'sh/yaroqsiz bo'lsa — "—". */
export function formatDateTime(iso: string | null | undefined): string {
  return toDate(iso)?.toLocaleString('uz-UZ') ?? '—';
}

/** Qisqa: "19.11, 14:30" (bosqichlar, xabarlar). Bo'sh bo'lsa — bo'sh qator. */
export function formatShortDateTime(iso: string | null | undefined): string {
  return (
    toDate(iso)?.toLocaleString('uz-UZ', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) ??
    ''
  );
}

/** Faqat soat:daqiqa. */
export function formatClock(iso: string | null | undefined): string {
  return toDate(iso)?.toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' }) ?? '';
}

/** Pul miqdori guruhlab ("1 250 000"); `fractionDigits` — kasr xonalari (standart 0). */
export function formatMoney(value: number, fractionDigits = 0): string {
  return new Intl.NumberFormat('uz-UZ', { maximumFractionDigits: fractionDigits }).format(value);
}
