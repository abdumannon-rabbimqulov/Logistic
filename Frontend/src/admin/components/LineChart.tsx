import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import styles from './LineChart.module.css';

// Bitta qatorli vaqt grafigi (SVG, kutubxonasiz). Sarlavha qatorni nomlaydi, shuning
// uchun legend yo'q. Kursor X bo'yicha eng yaqin nuqtaga "yopishadi" (crosshair) —
// 2px chiziqqa tegishga harakat qilish shart emas.

export interface LinePoint {
  t: number; // unix soniya
  v: number | null; // null — ma'lumot yo'q, chiziq uziladi
}

interface Props {
  title: string;
  points: LinePoint[];
  formatValue: (v: number) => string;
  /** Tooltip va o'q uchun vaqt formati. */
  formatTime: (t: number) => string;
  /** Y o'qi 0 dan boshlanadimi (son/miqdor uchun ha). */
  zeroBased?: boolean;
  /** Grafik ostidagi qisqa izoh. */
  note?: string;
  height?: number;
}

const PAD = { top: 12, right: 12, bottom: 24, left: 44 };

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  const f = v / exp;
  const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nice * exp;
}

export function LineChart({ title, points, formatValue, formatTime, zeroBased = true, note, height = 180 }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(480);
  const [hover, setHover] = useState<number | null>(null);

  // Kenglik mount paytida darhol (chizishdan oldin) o'lchanadi — ResizeObserver birinchi
  // xabarni kadr chizilgandan keyin beradi va ungacha SVG boshlang'ich 480px'da qolib,
  // tor kartadan chiqib ketardi. Keyingi o'zgarishlarni ResizeObserver kuzatadi.
  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    setWidth(Math.max(240, el.clientWidth));
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(240, entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const values = points.map((p) => p.v).filter((v): v is number => v !== null);
  const maxV = niceMax(values.length ? Math.max(...values) : 0);
  const minV = zeroBased ? 0 : Math.min(0, ...values);
  const innerW = width - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;

  const x = (i: number) => PAD.left + (points.length <= 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
  const y = (v: number) => PAD.top + innerH - ((v - minV) / (maxV - minV || 1)) * innerH;

  // Null qiymatda chiziq uziladi (M bilan yangi bo'lak) — "0" deb chizilmaydi,
  // aks holda "ma'lumot yo'q" bilan "so'rov yo'q" farqlanmay qolardi.
  const path = useMemo(() => {
    let d = '';
    let pen = false;
    points.forEach((p, i) => {
      if (p.v === null) {
        pen = false;
        return;
      }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`;
      pen = true;
    });
    return d;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, width, maxV, minV]);

  const ticks = [0, 0.5, 1].map((f) => minV + (maxV - minV) * f);
  const xLabelIdx = points.length > 1 ? [0, Math.floor((points.length - 1) / 2), points.length - 1] : [0];

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    if (!points.length) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const i = Math.round(((px - PAD.left) / innerW) * (points.length - 1));
    setHover(Math.max(0, Math.min(points.length - 1, i)));
  }

  function onKey(e: React.KeyboardEvent<SVGSVGElement>) {
    if (!points.length) return;
    if (e.key === 'ArrowLeft') setHover((h) => Math.max(0, (h ?? points.length) - 1));
    if (e.key === 'ArrowRight') setHover((h) => Math.min(points.length - 1, (h ?? -1) + 1));
  }

  const hp = hover !== null ? points[hover] : null;
  const latest = [...points].reverse().find((p) => p.v !== null);

  return (
    <figure className={styles.card}>
      <figcaption className={styles.head}>
        <span className={styles.title}>{title}</span>
        <span className={styles.latest}>{latest?.v != null ? formatValue(latest.v) : '—'}</span>
      </figcaption>
      <div ref={wrapRef} className={styles.plot}>
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`${title}: so'nggi qiymat ${latest?.v != null ? formatValue(latest.v) : "yo'q"}`}
          tabIndex={0}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
          onFocus={() => setHover((h) => h ?? points.length - 1)}
          onBlur={() => setHover(null)}
          onKeyDown={onKey}
        >
          {ticks.map((tv) => (
            <g key={tv}>
              <line className={styles.grid} x1={PAD.left} x2={width - PAD.right} y1={y(tv)} y2={y(tv)} />
              <text className={styles.axis} x={PAD.left - 6} y={y(tv)} dy="0.32em" textAnchor="end">
                {formatValue(tv)}
              </text>
            </g>
          ))}
          {xLabelIdx.map((i, k) =>
            points[i] ? (
              <text
                key={i}
                className={styles.axis}
                x={x(i)}
                y={height - 6}
                textAnchor={k === 0 ? 'start' : k === xLabelIdx.length - 1 ? 'end' : 'middle'}
              >
                {formatTime(points[i].t)}
              </text>
            ) : null,
          )}
          <path className={styles.line} d={path} />
          {hp && hover !== null && (
            <g>
              <line className={styles.crosshair} x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} />
              {hp.v !== null && <circle className={styles.dot} cx={x(hover)} cy={y(hp.v)} r={4} />}
            </g>
          )}
        </svg>
        {hp && hover !== null && (
          <div
            className={styles.tooltip}
            style={{
              left: Math.min(Math.max(x(hover), 70), width - 70),
            }}
          >
            <strong className={styles.tipValue}>{hp.v !== null ? formatValue(hp.v) : "ma'lumot yo'q"}</strong>
            <span className={styles.tipTime}>{formatTime(hp.t)}</span>
          </div>
        )}
      </div>
      {note && <div className={styles.note}>{note}</div>}
    </figure>
  );
}
