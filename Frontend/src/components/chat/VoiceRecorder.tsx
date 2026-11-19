import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { CHAT_LIMITS } from '../../api/chat';
import styles from './Chat.module.css';
import { formatDuration, isVoiceRecordingSupported, pickVoiceMime } from './mediaUtils';

interface Props {
  disabled?: boolean;
  onRecorded: (blob: Blob, durationS: number, mime: string) => void;
  onRecordingChange: (recording: boolean) => void;
  onError: (message: string) => void;
}

const CANCEL_SLIDE_PX = 90;
const MIN_DURATION_S = 0.7;

type Phase = 'idle' | 'starting' | 'recording';

/**
 * Ushlab turib yozish (Telegram'dagi kabi): mikrofon tugmasini bosib turing —
 * yoziladi, qo'yib yuborsangiz — yuboriladi, chapga sursangiz — bekor qilinadi.
 * 5 daqiqada o'zi to'xtab yuboriladi.
 *
 * Format: `MediaRecorder` qo'llaganini tanlaymiz — Android Chrome'da webm/opus,
 * iOS Safari'da mp4/aac (`pickVoiceMime`). Server baribir baytlardan tekshiradi.
 * Birinchi marta mikrofon ruxsati so'raladi — oyna chiqqanda barmoq qo'yib
 * yuborilgan bo'ladi, shuning uchun bu holatda yozuv boshlanmaydi va izoh ko'rsatiladi.
 */
export function VoiceRecorder({ disabled, onRecorded, onRecordingChange, onError }: Props) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [elapsed, setElapsed] = useState(0);
  const [cancelling, setCancelling] = useState(false);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef(0);
  const startXRef = useRef(0);
  const releasedRef = useRef(false);
  const cancellingRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopTracks = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  };

  const reset = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
    recorderRef.current = null;
    chunksRef.current = [];
    stopTracks();
    setPhase('idle');
    setElapsed(0);
    setCancelling(false);
    cancellingRef.current = false;
    onRecordingChange(false);
  };

  useEffect(() => () => {
    // Sahifadan chiqilsa — mikrofon yoqilgan holda qolmasin.
    if (timerRef.current) clearInterval(timerRef.current);
    try {
      recorderRef.current?.stop();
    } catch {
      /* allaqachon to'xtagan */
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
  }, []);

  const finish = (send: boolean) => {
    const recorder = recorderRef.current;
    if (!recorder) {
      reset();
      return;
    }
    const duration = (performance.now() - startedAtRef.current) / 1000;
    recorder.onstop = () => {
      const mime = recorder.mimeType || pickVoiceMime() || 'audio/webm';
      const blob = new Blob(chunksRef.current, { type: mime });
      reset();
      if (!send) return;
      if (duration < MIN_DURATION_S || blob.size === 0) {
        onError('Yozish uchun tugmani bosib turing');
        return;
      }
      onRecorded(blob, Math.min(duration, CHAT_LIMITS.voiceSeconds), mime);
    };
    try {
      recorder.stop();
    } catch {
      reset();
    }
  };

  const start = async () => {
    if (!isVoiceRecordingSupported()) {
      onError("Bu qurilmada ovoz yozib bo'lmaydi");
      return;
    }
    releasedRef.current = false;
    setPhase('starting');
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setPhase('idle');
      onError("Mikrofonga ruxsat berilmagan. Telefon sozlamalaridan ruxsat bering.");
      return;
    }
    streamRef.current = stream;
    if (releasedRef.current) {
      // Ruxsat oynasi paytida barmoq qo'yib yuborildi — endi qayta bosib turing.
      stopTracks();
      setPhase('idle');
      onError('Ruxsat berildi. Endi yozish uchun tugmani bosib turing.');
      return;
    }
    const mime = pickVoiceMime();
    let recorder: MediaRecorder;
    try {
      recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    } catch {
      stopTracks();
      setPhase('idle');
      onError("Ovoz yozishni boshlab bo'lmadi");
      return;
    }
    chunksRef.current = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    recorder.start(250);
    recorderRef.current = recorder;
    startedAtRef.current = performance.now();
    setPhase('recording');
    onRecordingChange(true);
    window.Telegram?.WebApp?.HapticFeedback?.impactOccurred('light');
    timerRef.current = setInterval(() => {
      const secs = (performance.now() - startedAtRef.current) / 1000;
      setElapsed(secs);
      if (secs >= CHAT_LIMITS.voiceSeconds) finish(true);
    }, 200);
  };

  const onPointerDown = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (disabled || phase !== 'idle') return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    startXRef.current = e.clientX;
    void start();
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (phase !== 'recording') return;
    const next = e.clientX - startXRef.current < -CANCEL_SLIDE_PX;
    if (next !== cancellingRef.current) {
      cancellingRef.current = next;
      setCancelling(next);
      if (next) window.Telegram?.WebApp?.HapticFeedback?.selectionChanged();
    }
  };

  const onPointerUp = () => {
    releasedRef.current = true;
    if (phase === 'recording') finish(!cancellingRef.current);
  };

  return (
    <>
      {phase === 'recording' && (
        <div className={styles.recording}>
          <span className={styles.recDot} />
          <span>{formatDuration(elapsed)}</span>
          <span className={`${styles.recHint} ${cancelling ? styles.recHintCancel : ''}`}>
            {cancelling ? "Qo'yib yuboring — bekor qilinadi" : '‹ Bekor qilish uchun chapga suring'}
          </span>
        </div>
      )}
      <button
        type="button"
        className={`${styles.iconBtn} ${phase === 'recording' ? styles.micActive : ''}`}
        disabled={disabled}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => {
          releasedRef.current = true;
          if (phase === 'recording') finish(false);
        }}
        onContextMenu={(e) => e.preventDefault()}
        aria-label="Ovozli xabar (bosib turing)"
      >
        🎤
      </button>
    </>
  );
}
