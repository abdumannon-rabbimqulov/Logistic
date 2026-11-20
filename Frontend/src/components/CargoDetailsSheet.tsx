import { useRef, useState, type FormEvent } from 'react';
import {
  describePickupAt,
  fromDateTimeLocalValue,
  maxPickupValue,
  minPickupValue,
  PICKUP_PRESETS,
  toDateTimeLocalValue,
  validatePickupAt,
} from '../utils/pickupTime';
import type { UnloadingMode } from '../types/api';
import { formatPrice } from '../utils/format';
import { BottomSheetModal } from './BottomSheetModal';
import styles from './CargoDetailsSheet.module.css';

export interface CargoDetails {
  cargoName: string;
  weight: number;
  volume?: number;
  /** Yuk tayyor bo'ladigan payt — backendga ISO 8601 bo'lib ketadi (`pickup_at`). */
  pickupAt: Date;
  /** Manzilda tushirish sharti — ixtiyoriy, tanlanmasa yuborilmaydi. */
  unloadingMode?: UnloadingMode;
  /** Faqat "bir necha soat" varianti bilan (backend aks holda 422 qaytaradi). */
  unloadingWaitHours?: number;
}

// Tushirish shartlari — mijoz faqat BITTASINI tanlaydi va tanlamasligi ham mumkin.
// Matnlar haydovchi ko'radigan qilib yozilgan: uning uchun bu reysdan keyin mashina
// qancha band bo'lishini bildiradi.
const UNLOADING_OPTIONS: { value: UnloadingMode; label: string }[] = [
  { value: 'IMMEDIATE', label: "O'sha zahoti tushirish" },
  { value: 'HOURS', label: 'Bir necha soat kutish' },
  { value: 'DAY', label: 'Kun kutish' },
];

// `MAX_UNLOADING_WAIT_HOURS` (order/schemas.py) bilan bir xil: undan oshsa bu
// allaqachon "kun kutish" varianti.
const MAX_WAIT_HOURS = 24;

/** Tanlangan shartning qisqa izohi — "Yuk qachon tayyor" qismidagi kabi, foydalanuvchi
 *  yuborishdan oldin nima tanlaganini bir qatorda ko'rib tursin. */
function describeUnloading(mode: UnloadingMode, waitHours: string): string {
  if (mode === 'HOURS') {
    const hours = waitHours.trim();
    return hours ? `${hours} soat kutish` : 'Bir necha soat kutish';
  }
  return UNLOADING_OPTIONS.find((o) => o.value === mode)?.label ?? '—';
}

interface Props {
  onSubmit: (details: CargoDetails) => void;
  onClose: () => void;
  submitting: boolean;
  apiError?: string | null;
  /** Og'irlik o'zgarganda chaqiriladi — sahifa narxni shu og'irlik bilan qayta so'raydi. */
  onWeightChange?: (weight: number | null) => void;
  /** Tanlangan mashina uchun joriy (og'irlik hisobga olingan) narx. */
  price?: number | null;
  priceLoading?: boolean;
}

// Dizaynda yuk tafsilotlari uchun alohida ekran yo'q, lekin backend `OrderCreate` buni talab
// qiladi (cargo_name, weight) — shuning uchun "Buyurtma berish" bosilganda shu kichik forma
// so'raladi (minimal, dizayn tokenlariga mos).
export function CargoDetailsSheet({ onSubmit, onClose, submitting, apiError, onWeightChange, price, priceLoading }: Props) {
  const [cargoName, setCargoName] = useState('');
  const [weight, setWeight] = useState('');
  const [volume, setVolume] = useState('');
  const [error, setError] = useState<string | null>(null);
  // Standart holat — "Hozir". Ilgari vaqt umuman so'ralmasdi va buyurtma har doim
  // "darhol tayyor" bo'lib ketardi (OrderPage `new Date()` yozib yuborardi).
  const [pickupAt, setPickupAt] = useState<Date>(() => new Date());
  // Kalendar faqat "Boshqa vaqt" tanlanganda ochiladi — odatiy holat uchun
  // bitta bosish yetarli bo'lsin.
  const [customOpen, setCustomOpen] = useState(false);
  // Tushirish sharti — ixtiyoriy, shuning uchun standart holat `null` ("tanlanmagan").
  const [unloadingMode, setUnloadingMode] = useState<UnloadingMode | null>(null);
  const [waitHours, setWaitHours] = useState('');
  const [errorField, setErrorField] = useState<'cargoName' | 'weight' | 'volume' | 'pickupAt' | 'waitHours' | null>(null);
  const cargoNameRef = useRef<HTMLInputElement>(null);
  const weightRef = useRef<HTMLInputElement>(null);
  const volumeRef = useRef<HTMLInputElement>(null);
  const pickupRef = useRef<HTMLInputElement>(null);
  const waitHoursRef = useRef<HTMLInputElement>(null);

  function selectUnloadingMode(mode: UnloadingMode) {
    // Tanlangan variantni qayta bosish — bekor qilish. Aks holda foydalanuvchi bir
    // marta bosgandan keyin "hech qanday shart yo'q" holatiga qaytolmasdi.
    const next = unloadingMode === mode ? null : mode;
    setUnloadingMode(next);
    if (next !== 'HOURS') setWaitHours('');
    setError(null);
  }

  function selectPreset(build: () => Date) {
    setPickupAt(build());
    setCustomOpen(false);
    setError(null);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    const weightNum = Number(weight.replace(',', '.'));
    const fail = (message: string, field: NonNullable<typeof errorField>, input: HTMLInputElement | null) => {
      setError(message);
      setErrorField(field);
      input?.focus();
    };
    if (!cargoName.trim()) {
      fail('Yuk nomini kiriting', 'cargoName', cargoNameRef.current);
      return;
    }
    if (!weightNum || weightNum <= 0) {
      fail("Yuk og'irligini to'g'ri kiriting", 'weight', weightRef.current);
      return;
    }
    const volumeNum = volume.trim() ? Number(volume.replace(',', '.')) : undefined;
    if (volumeNum !== undefined && (!Number.isFinite(volumeNum) || volumeNum <= 0)) {
      fail('Hajmni musbat son bilan kiriting yoki maydonni bo‘sh qoldiring', 'volume', volumeRef.current);
      return;
    }
    // "Hozir" tanlanib forma uzoq ochiq turgan bo'lsa vaqt o'tib ketishi mumkin —
    // shuning uchun yuborishdan oldin qayta tekshiriladi (server ham tekshiradi).
    const pickupError = validatePickupAt(pickupAt);
    if (pickupError) {
      fail(pickupError, 'pickupAt', pickupRef.current);
      return;
    }
    // Kutish soati ixtiyoriy: bo'sh qoldirilsa shart "bir necha soat" bo'lib qolaveradi.
    const waitNum = waitHours.trim() ? Number(waitHours.replace(',', '.')) : undefined;
    if (unloadingMode === 'HOURS' && waitNum !== undefined) {
      if (!Number.isInteger(waitNum) || waitNum < 1 || waitNum > MAX_WAIT_HOURS) {
        fail(`Kutish vaqtini 1 dan ${MAX_WAIT_HOURS} soatgacha butun son bilan kiriting`, 'waitHours', waitHoursRef.current);
        return;
      }
    }
    setError(null);
    setErrorField(null);
    onSubmit({
      cargoName: cargoName.trim(),
      weight: weightNum,
      volume: volumeNum && volumeNum > 0 ? volumeNum : undefined,
      pickupAt,
      unloadingMode: unloadingMode ?? undefined,
      unloadingWaitHours: unloadingMode === 'HOURS' ? waitNum : undefined,
    });
  }

  return (
    <BottomSheetModal title="Yuk tafsilotlari" onClose={onClose}>
      <form noValidate onSubmit={handleSubmit}>
      <div className={styles.field}>
        <label className={styles.label} htmlFor="cargo-name">Yuk nomi</label>
        <input ref={cargoNameRef} id="cargo-name" name="cargo_name" className={styles.input} value={cargoName} onChange={(e) => { setCargoName(e.target.value); if (errorField === 'cargoName') { setError(null); setErrorField(null); } }} placeholder="Masalan: mebel, oziq-ovqat..." aria-invalid={errorField === 'cargoName' || undefined} aria-describedby={errorField === 'cargoName' ? 'cargo-error' : undefined} required />
      </div>
      <div className={styles.row}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="cargo-weight">Og'irligi (tonna)</label>
          <input
            ref={weightRef}
            id="cargo-weight"
            name="weight"
            className={styles.input}
            inputMode="decimal"
            value={weight}
            onChange={(e) => {
              setWeight(e.target.value);
              if (errorField === 'weight') { setError(null); setErrorField(null); }
              const n = Number(e.target.value.replace(',', '.'));
              onWeightChange?.(Number.isFinite(n) && n > 0 ? n : null);
            }}
            placeholder="1.5"
            aria-invalid={errorField === 'weight' || undefined}
            aria-describedby={errorField === 'weight' ? 'cargo-error' : undefined}
            required
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Hajmi, m³ (ixtiyoriy)</label>
          <input
            ref={volumeRef}
            id="cargo-volume"
            name="volume"
            className={styles.input}
            inputMode="decimal"
            value={volume}
            onChange={(e) => { setVolume(e.target.value); if (errorField === 'volume') { setError(null); setErrorField(null); } }}
            placeholder="—"
            aria-invalid={errorField === 'volume' || undefined}
            aria-describedby={errorField === 'volume' ? 'cargo-error' : undefined}
          />
        </div>
      </div>
      {price != null && (
        <div className={styles.pricePreview} aria-live="polite">
          <span>Narx (og'irlik bilan)</span>
          <strong className={priceLoading ? styles.pricePreviewLoading : undefined}>{formatPrice(price)} so'm</strong>
        </div>
      )}
      <div className={styles.field}>
        <div className={styles.label} id="pickup-options-label">Yuk qachon tayyor bo'ladi?</div>
        <div className={styles.presets} role="group" aria-labelledby="pickup-options-label">
          {PICKUP_PRESETS.map((preset) => {
            const candidate = preset.build();
            // Tanlangan variant ajratib ko'rsatiladi. Daqiqagacha aniqlik shart emas —
            // "Hozir" har renderda yangi vaqt beradi, shuning uchun taqqoslash
            // daqiqa darajasida qilinadi.
            const active =
              !customOpen &&
              Math.abs(candidate.getTime() - pickupAt.getTime()) < 60_000;
            return (
              <button
                key={preset.label}
                type="button"
                className={active ? styles.presetActive : styles.preset}
                onClick={() => selectPreset(preset.build)}
              >
                {preset.label}
              </button>
            );
          })}
          <button
            type="button"
            className={customOpen ? styles.presetActive : styles.preset}
            onClick={() => setCustomOpen(true)}
          >
            Boshqa vaqt
          </button>
        </div>

        {customOpen && (
          <div className={styles.field}>
          <label className={styles.label} htmlFor="pickup-time">Sana va vaqt</label>
          <input
            ref={pickupRef}
            id="pickup-time"
            name="pickup_at"
            className={styles.input}
            type="datetime-local"
            value={toDateTimeLocalValue(pickupAt)}
            min={minPickupValue()}
            max={maxPickupValue()}
            aria-invalid={errorField === 'pickupAt' || undefined}
            aria-describedby={errorField === 'pickupAt' ? 'cargo-error' : undefined}
            onChange={(e) => {
              const next = fromDateTimeLocalValue(e.target.value);
              if (next) {
                setPickupAt(next);
                const pickupError = validatePickupAt(next);
                setError(pickupError);
                setErrorField(pickupError ? 'pickupAt' : null);
              }
            }}
          />
          </div>
        )}

        <div className={styles.pickupSummary}>Tanlandi: {describePickupAt(pickupAt)}</div>
      </div>

      <div className={styles.field}>
        <label className={styles.label}>Manzilda yukni tushirish (ixtiyoriy)</label>
        <div className={styles.presets}>
          {UNLOADING_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={unloadingMode === option.value ? styles.presetActive : styles.preset}
              onClick={() => selectUnloadingMode(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>

        {unloadingMode === 'HOURS' && (
          <div className={styles.field}>
          <label className={styles.label} htmlFor="unloading-wait-hours">Kutish vaqti (soat)</label>
          <input
            ref={waitHoursRef}
            id="unloading-wait-hours"
            name="unloading_wait_hours"
            className={styles.input}
            inputMode="numeric"
            value={waitHours}
            onChange={(e) => { setWaitHours(e.target.value); if (errorField === 'waitHours') { setError(null); setErrorField(null); } }}
            placeholder={`Taxminiy kutish, soat (1–${MAX_WAIT_HOURS}) — ixtiyoriy`}
            aria-label="Kutish vaqti, soat"
            aria-invalid={errorField === 'waitHours' || undefined}
            aria-describedby={errorField === 'waitHours' ? 'cargo-error' : undefined}
          />
          </div>
        )}

        <div className={styles.pickupSummary}>
          {unloadingMode === null
            ? "Tanlanmagan — haydovchiga qo'shimcha shart qo'yilmaydi"
            : `Tanlandi: ${describeUnloading(unloadingMode, waitHours)}`}
        </div>
      </div>

      {(error || apiError) && <div id="cargo-error" className={styles.error} role="alert">{error ?? apiError}</div>}
      <button type="submit" className={styles.submitBtn} disabled={submitting} aria-busy={submitting}>
        {submitting ? 'Yuborilmoqda...' : 'Tasdiqlash'}
      </button>
      </form>
    </BottomSheetModal>
  );
}
