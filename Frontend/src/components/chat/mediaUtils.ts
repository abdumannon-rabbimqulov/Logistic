// Chat uchun brauzerdagi media yordamchilari: rasmni siqish, video poster kadri,
// ovoz yozish formati, vaqt/hajm formatlari.

const PHOTO_MAX_PX = 1600;
const PHOTO_QUALITY = 0.82;

/** Rasmni ≤1600px JPEG ga siqadi (kamera rasmi 4–8 MB → ~300 KB). EXIF burilishi
 *  hisobga olinadi. Siqib bo'lmasa (HEIC'ni o'qiy olmaydigan brauzer) — asl fayl. */
export async function compressImage(file: File): Promise<{ blob: Blob; width: number; height: number }> {
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
    const scale = Math.min(1, PHOTO_MAX_PX / Math.max(bitmap.width, bitmap.height));
    const width = Math.round(bitmap.width * scale);
    const height = Math.round(bitmap.height * scale);
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('canvas');
    ctx.drawImage(bitmap, 0, 0, width, height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', PHOTO_QUALITY));
    if (!blob) throw new Error('toBlob');
    // Siqilgan versiya kattaroq chiqsa (kichik PNG) — aslini yuboramiz.
    return blob.size < file.size ? { blob, width, height } : { blob: file, width, height };
  } catch {
    return { blob: file, width: 0, height: 0 };
  }
}

/** Video'ning birinchi kadrlaridan poster (JPEG) va davomiylik. Bo'lmasa — null. */
export function videoPoster(file: File): Promise<{ poster: Blob | null; duration: number | null }> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement('video');
    video.preload = 'metadata';
    video.muted = true;
    video.playsInline = true;
    video.src = url;
    let done = false;
    const finish = (poster: Blob | null) => {
      if (done) return;
      done = true;
      const duration = Number.isFinite(video.duration) ? video.duration : null;
      URL.revokeObjectURL(url);
      resolve({ poster, duration });
    };
    const timer = setTimeout(() => finish(null), 5000);
    video.onloadeddata = () => {
      // 0-kadr ko'pincha qora — biroz oldinga suramiz.
      video.currentTime = Math.min(0.5, (video.duration || 1) / 2);
    };
    video.onseeked = () => {
      clearTimeout(timer);
      try {
        const scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight));
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
        canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
        canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((b) => finish(b), 'image/jpeg', 0.75);
      } catch {
        finish(null);
      }
    };
    video.onerror = () => {
      clearTimeout(timer);
      finish(null);
    };
  });
}

/** MediaRecorder qo'llaydigan ovoz formati: Android Chrome — webm/opus,
 *  iOS Safari — mp4/aac. Hech biri aniq bo'lmasa — brauzer standarti (''). */
export function pickVoiceMime(): string {
  if (typeof MediaRecorder === 'undefined') return '';
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/aac', 'audio/ogg;codecs=opus'];
  return candidates.find((m) => MediaRecorder.isTypeSupported?.(m)) ?? '';
}

export function voiceFileName(mime: string): string {
  if (mime.includes('mp4') || mime.includes('aac')) return 'voice.m4a';
  if (mime.includes('ogg')) return 'voice.ogg';
  return 'voice.webm';
}

export function isVoiceRecordingSupported(): boolean {
  return typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
}

export function formatDuration(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.round(seconds ?? 0));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const MONTHS = [
  'yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun',
  'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr',
];

/** Lenta ajratgichi: "Bugun", "Kecha", "12-noyabr" (boshqa yil bo'lsa yil bilan). */
export function dayLabel(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diffDays = Math.round((startOf(now) - startOf(d)) / 86_400_000);
  if (diffDays === 0) return 'Bugun';
  if (diffDays === 1) return 'Kecha';
  const base = `${d.getDate()}-${MONTHS[d.getMonth()]}`;
  return d.getFullYear() === now.getFullYear() ? base : `${base}, ${d.getFullYear()}`;
}

export function dayKey(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

export function timeLabel(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** Matndagi telefon raqamlari va havolalarni bosiladigan qiladi (raqamlar
 *  yashirilmaydi — talab). Qaytaradi: oddiy matn va havola bo'laklari. */
export type TextPart = { text: string; href?: string };

const LINK_RE = /(https?:\/\/[^\s]+)|(\+?\d[\d\s\-()]{7,}\d)/g;

export function linkify(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let last = 0;
  for (const match of text.matchAll(LINK_RE)) {
    const start = match.index ?? 0;
    if (start > last) parts.push({ text: text.slice(last, start) });
    const value = match[0];
    if (match[1]) {
      parts.push({ text: value, href: value });
    } else {
      const digits = value.replace(/[^\d+]/g, '');
      // 9+ raqam — telefon; aks holda (summa, sana) oddiy matn.
      parts.push(digits.replace('+', '').length >= 9 ? { text: value, href: `tel:${digits}` } : { text: value });
    }
    last = start + value.length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}

export function mapUrl(lat: number, lon: number): string {
  return `https://yandex.uz/maps/?pt=${lon},${lat}&z=16&l=map`;
}
