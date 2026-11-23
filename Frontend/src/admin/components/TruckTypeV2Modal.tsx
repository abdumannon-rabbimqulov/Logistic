import { useEffect, useState } from 'react';
import type { TruckType } from '../../types/api';
import { ApiError } from '../../api/client';
import {
  listPricingV2Versions, previewPricingV2, publishPricingV2, savePricingV2Draft,
  type PricingV2Draft, type PricingV2Result, type PricingV2Costs, type PricingV2Rules,
  type PricingV2PreviewRequest, type PricingV2Version,
} from '../../api/pricingV2';
import { Modal } from './Modal';
import styles from './TruckTypeFormModal.module.css';

const COST_LABELS: { key: keyof PricingV2Costs; label: string; hint: string }[] = [
  { key: 'fuel_uzs_per_liter', label: "Yoqilg‘i (so‘m/litr)", hint: 'Haqiqiy xarid narxi' },
  { key: 'loaded_liters_per_100_km', label: "Yuk bilan sarf (l/100 km)", hint: 'Texnik sarf' },
  { key: 'empty_liters_per_100_km', label: "Bo‘sh sarf (l/100 km)", hint: 'Texnik sarf' },
  { key: 'operation_uzs_per_km', label: "Ekspluatatsiya (so‘m/km)", hint: 'Servis, amortizatsiya' },
  { key: 'driving_uzs_per_hour', label: "Haydovchi (so‘m/soat)", hint: 'Yo‘lda ketgan vaqt' },
  { key: 'loading_uzs_per_hour', label: "Yuklash (so‘m/soat)", hint: 'Yuklash ish haqi' },
  { key: 'unloading_uzs_per_hour', label: "Tushirish (so‘m/soat)", hint: 'Tushirish xarajati' },
  { key: 'waiting_uzs_per_hour', label: "Kutish (so‘m/soat)", hint: 'Bekor turish xarajati' },
  { key: 'handling_uzs_per_ton', label: "Ishlov (so‘m/tonna)", hint: 'Alohida yuk ishlovi' },
  { key: 'handling_uzs_per_m3', label: "Ishlov (so‘m/m³)", hint: 'Hajmga bog‘liq ishlov' },
];

const RULE_LABELS: { key: 'minimum_price_uzs' | 'target_margin_uzs' | 'minimum_net_margin_uzs' | 'commission_rate'; label: string; hint: string }[] = [
  { key: 'minimum_price_uzs', label: "Minimal narx (so‘m)", hint: '0 dan katta' },
  { key: 'target_margin_uzs', label: "Maqsadli marja (so‘m)", hint: 'Xarajatlarga qo‘shiladi' },
  { key: 'minimum_net_margin_uzs', label: "Sof minimal marja (so‘m)", hint: 'Komissiyadan keyin' },
  { key: 'commission_rate', label: 'Komissiya ulushi (0–1)', hint: 'Masalan 0.1 = 10%' },
];

const emptyDraft = (): PricingV2Draft => ({
  costs: Object.fromEntries(COST_LABELS.map(({ key }) => [key, ''])) as unknown as PricingV2Costs,
  rules: {
    minimum_price_uzs: '', target_margin_uzs: '', minimum_net_margin_uzs: '',
    commission_rate: '', route_bounds: { minimum: '1', maximum: '1' },
    demand_bounds: { minimum: '1', maximum: '1' },
  },
  configured_empty_run: null,
});

type Example = Omit<PricingV2PreviewRequest, 'profile'>;
const defaultExample = (truck: TruckType): Example => ({
  distance_km: '100', duration_min: '120',
  weight_t: String(Math.min(truck.max_weight, 1)),
  volume_m3: null, loading_min: '0', unloading_min: '0', waiting_min: '0',
  regional_factor: '1', demand_signal: '1',
});

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : 'So‘rov bajarilmadi';
}

function validNumber(v: string, positive = false): boolean {
  if (!/^\d+(\.\d+)?$/.test(v)) return false;
  const n = Number(v);
  return Number.isFinite(n) && (positive ? n > 0 : n >= 0);
}

function validDraft(draft: PricingV2Draft): string | null {
  for (const { key, label } of COST_LABELS) {
    if (!validNumber(draft.costs[key])) return label + ' maydoniga musbat yoki 0 qiymat kiriting';
  }
  for (const { key, label } of RULE_LABELS) {
    if (!validNumber(draft.rules[key], key === 'minimum_price_uzs')) return label + ' noto‘g‘ri';
  }
  const r = draft.rules;
  if (+r.commission_rate >= 1 || +r.minimum_net_margin_uzs > +r.target_margin_uzs) {
    return 'Komissiya 1 dan kichik va maqsadli marja minimal marjadan kam bo‘lmasin';
  }
  for (const key of ['route_bounds', 'demand_bounds'] as const) {
    const b = r[key];
    if (!validNumber(b.minimum, true) || !validNumber(b.maximum, true)
      || +b.minimum > 1 || +b.maximum < 1) return 'Koeffitsiyent chegaralari 1 ni o‘z ichiga olishi kerak';
  }
  if (draft.configured_empty_run && (!validNumber(draft.configured_empty_run.distance_km)
    || !validNumber(draft.configured_empty_run.duration_min))) return 'Bo‘sh yurish raqamlarini tekshiring';
  return null;
}

export function TruckTypeV2Modal({ truck, onClose }: { truck: TruckType; onClose: () => void }) {
  const [draft, setDraft] = useState<PricingV2Draft>(emptyDraft);
  const [example, setExample] = useState<Example>(() => defaultExample(truck));
  const [versions, setVersions] = useState<PricingV2Version[]>([]);
  const [result, setResult] = useState<PricingV2Result | null>(null);
  const [previewed, setPreviewed] = useState(false);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listPricingV2Versions(truck.id).then(rows => {
      if (!active) return;
      setVersions(rows);
      if (rows.length) { setDraft(rows[0].profile); setSaved(rows[0].status === 'draft'); }
    }).catch(err => { if (active) setError(errorMessage(err)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [truck.id]);

  function changeDraft(next: PricingV2Draft) {
    setDraft(next); setPreviewed(false); setResult(null); setSaved(false); setInfo(null);
  }
  function changeExample(next: Example) {
    setExample(next); setPreviewed(false); setResult(null); setInfo(null);
  }
  async function doPreview() {
    const problem = validDraft(draft);
    if (problem) { setError(problem); return; }
    setBusy(true); setError(null); setInfo(null);
    try {
      const calculated = await previewPricingV2(truck.id, { profile: draft, ...example });
      setResult(calculated); setPreviewed(true);
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  async function doSave() {
    const problem = validDraft(draft);
    if (problem) { setError(problem); return; }
    setBusy(true); setError(null);
    try {
      const row = await savePricingV2Draft(truck.id, draft);
      setSaved(true); setInfo('Draft v' + row.version + ' saqlandi. Bu amaldagi buyurtma narxiga ta’sir qilmaydi.');
      setVersions(await listPricingV2Versions(truck.id));
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }
  async function doPublish() {
    if (!previewed || !saved) return;
    setBusy(true); setError(null);
    try {
      const p = await publishPricingV2(truck.id);
      setInfo('V2 tarif v' + p.version + ' e’lon qilindi. Python V1 hali buyurtmalarda faol.');
      setSaved(false); setPreviewed(false);
      setVersions(await listPricingV2Versions(truck.id));
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }

  const numberInput = (label: string, value: string, onChange: (value: string) => void, hint?: string) => (
    <label className={styles.field} key={label}>
      <span className={styles.label}>{label}</span>
      <input className={styles.input} type="number" inputMode="decimal" min="0"
        value={value} placeholder="Qiymat kiriting" onChange={e => onChange(e.target.value)} />
      {hint && <small>{hint}</small>}
    </label>
  );

  return (
    <Modal title={truck.name + ' — Go Pricing V2 tarifi'} onClose={onClose}
      footer={<div style={{ display: 'flex', justifyContent: 'flex-end', flexWrap: 'wrap', gap: 8 }}>
        <button className={styles.cancelBtn} onClick={onClose} disabled={busy}>Yopish</button>
        <button className={styles.cancelBtn} disabled={busy || loading} onClick={doPreview}>Narxni hisoblash</button>
        <button className={styles.saveBtn} disabled={busy || loading} onClick={doSave}>Draft saqlash</button>
        <button className={styles.saveBtn} disabled={busy || !saved || !previewed} onClick={doPublish}>E’lon qilish</button>
      </div>}>
      <p>Transport sig‘imi: <b>{truck.max_weight} t / {truck.max_volume} m³</b>. Tarif versiyalari V1 narxini o‘zgartirmaydi.</p>
      {loading && <p>Tariflar yuklanmoqda…</p>}
      {error && <div role="alert" className={styles.error}>{error}</div>}
      {info && <p role="status">{info}</p>}
      {versions.length > 0 && <details>
        <summary>Tariflar tarixi — {versions.length} ta versiya (oxirgisi v{versions[0].version})</summary>
        <ul>{versions.map(v => <li key={v.id}>
          v{v.version} · {v.status === 'published' ? 'E’lon qilingan' : 'Draft'} ·
          {' '}{new Date(v.created_at).toLocaleString('uz-UZ')}
        </li>)}</ul>
      </details>}
      <h4>1. Xarajatlar</h4>
      <div className={styles.grid2}>
        {COST_LABELS.map(({ key, label, hint }) => numberInput(label, draft.costs[key], value =>
          changeDraft({ ...draft, costs: { ...draft.costs, [key]: value } }), hint))}
      </div>
      <h4>2. Tarif qoidalari</h4>
      <div className={styles.grid2}>
        {RULE_LABELS.map(({ key, label, hint }) => numberInput(label, draft.rules[key], value =>
          changeDraft({ ...draft, rules: { ...draft.rules, [key]: value } as PricingV2Rules }), hint))}
      </div>
      <h4>3. Koeffitsiyentlar (1 = narx o‘zgarmaydi)</h4>
      <div className={styles.grid2}>
        {(['route_bounds', 'demand_bounds'] as const).flatMap(key =>
          (['minimum', 'maximum'] as const).map(bound =>
            numberInput((key === 'route_bounds' ? 'Hududiy' : 'Talab') + ' ' + bound,
              draft.rules[key][bound], value => changeDraft({
                ...draft, rules: { ...draft.rules, [key]: { ...draft.rules[key], [bound]: value } },
              }))))}
      </div>
      <h4>4. Bo‘sh yurish (ixtiyoriy)</h4>
      <label className={styles.switchRow}>
        <input type="checkbox" checked={draft.configured_empty_run !== null} onChange={e =>
          changeDraft({ ...draft, configured_empty_run: e.target.checked ? { distance_km: '0', duration_min: '0' } : null })} />
        Bo‘sh yurishni tarifga qo‘shish
      </label>
      {draft.configured_empty_run && <div className={styles.grid2}>
        {numberInput('Masofa, km', draft.configured_empty_run.distance_km, value => changeDraft({
          ...draft, configured_empty_run: { ...draft.configured_empty_run!, distance_km: value },
        }))}
        {numberInput('Vaqt, daqiqa', draft.configured_empty_run.duration_min, value => changeDraft({
          ...draft, configured_empty_run: { ...draft.configured_empty_run!, duration_min: value },
        }))}
      </div>}
      <h4>5. Server orqali narxni sinash</h4>
      <p>Quyidagi masofa va vaqt faqat sinov misoli. Buyurtmalarga qo‘llanmaydi.</p>
      <div className={styles.grid2}>
        {([
          ['distance_km', 'Masofa, km'], ['duration_min', 'Vaqt, daqiqa'],
          ['weight_t', 'Yuk, tonna'], ['loading_min', 'Yuklash, daqiqa'],
          ['unloading_min', 'Tushirish, daqiqa'], ['waiting_min', 'Kutish, daqiqa'],
        ] as const).map(([key, label]) => numberInput(label, example[key], value => changeExample({ ...example, [key]: value })))}
        {numberInput('Yuk hajmi, m³ (ixtiyoriy)', example.volume_m3 ?? '', value =>
          changeExample({ ...example, volume_m3: value.trim() ? value : null }))}
        {numberInput('Hududiy koeffitsiyent', example.regional_factor, value =>
          changeExample({ ...example, regional_factor: value }))}
        {numberInput('Talab koeffitsiyenti', example.demand_signal, value =>
          changeExample({ ...example, demand_signal: value }))}
      </div>
      {result && <div role="status" className={styles.priceBox}>
        <b>Go V2 tavsiya qilgan narx: {result.recommended_price} so‘m</b>
        <p>Xarajat: {result.costs.total} so‘m · Komissiya: {result.expected_commission} so‘m</p>
        <p>Kutilayotgan sof marja: {result.expected_net_margin} so‘m</p>
      </div>}
      <p><small>Preview ishlashi uchun Go Pricing servisi va serverdagi PRICING_GO_URL / PRICING_SERVICE_TOKEN sozlangan bo‘lishi kerak.</small></p>
    </Modal>
  );
}
