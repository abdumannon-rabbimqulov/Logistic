import { memo, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import styles from './Chat.module.css';
import { formatBytes, formatDuration, linkify, mapUrl, timeLabel } from './mediaUtils';
import type { UiMessage } from './types';

interface Props {
  message: UiMessage;
  mine: boolean;
  /** Sherigim shu id gacha o'qigan — ✓✓ uchun. */
  peerLastReadId: number;
  /** Reply iqtibosidagi muallif nomi uchun. */
  nameOf: (userId: number) => string;
  highlighted?: boolean;
  onOpenMedia: (message: UiMessage) => void;
  onQuoteClick: (messageId: number) => void;
  onMenu: (message: UiMessage) => void;
}

const LONG_PRESS_MS = 450;
const MOVE_TOLERANCE_PX = 10;

function MessageBubbleInner({
  message,
  mine,
  peerLastReadId,
  nameOf,
  highlighted,
  onOpenMedia,
  onQuoteClick,
  onMenu,
}: Props) {
  const pressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pressStart = useRef<{ x: number; y: number } | null>(null);
  const longPressed = useRef(false);

  const cancelPress = () => {
    if (pressTimer.current) clearTimeout(pressTimer.current);
    pressTimer.current = null;
    pressStart.current = null;
  };

  const onPointerDown = (e: ReactPointerEvent) => {
    longPressed.current = false;
    pressStart.current = { x: e.clientX, y: e.clientY };
    pressTimer.current = setTimeout(() => {
      longPressed.current = true;
      window.Telegram?.WebApp?.HapticFeedback?.impactOccurred('medium');
      onMenu(message);
    }, LONG_PRESS_MS);
  };

  const onPointerMove = (e: ReactPointerEvent) => {
    const start = pressStart.current;
    if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > MOVE_TOLERANCE_PX) cancelPress();
  };

  const deleted = message.deleted_at != null;
  const status = message.local?.status;
  const isMedia = !deleted && (message.kind === 'photo' || message.kind === 'video');
  const overlayMeta = isMedia && !message.text;

  const ticks = mine && !status && !deleted && (
    <span className={`${styles.ticks} ${message.id <= peerLastReadId ? styles.ticksRead : ''}`}>
      {message.id <= peerLastReadId ? '✓✓' : '✓'}
    </span>
  );

  const meta = (
    <span className={`${styles.meta} ${overlayMeta ? styles.metaOverlay : ''}`}>
      {message.edited_at && !deleted && <span>tahrirlangan</span>}
      <span>{timeLabel(message.created_at)}</span>
      {status === 'sending' && <span>🕓</span>}
      {status === 'failed' && <span className={styles.failed}>!</span>}
      {ticks}
    </span>
  );

  // Muvaffaqiyatsiz xabarga bosish — qayta yuborish menyusi.
  const handleClick = () => {
    if (longPressed.current) return;
    if (status === 'failed') onMenu(message);
  };

  return (
    <div className={`${styles.row} ${mine ? styles.rowMine : ''}`} data-mid={message.id}>
      <div
        className={`${styles.bubble} ${isMedia ? styles.bubbleMedia : ''} ${highlighted ? styles.highlight : ''}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={cancelPress}
        onPointerCancel={cancelPress}
        onPointerLeave={cancelPress}
        onContextMenu={(e) => {
          e.preventDefault();
          cancelPress();
          onMenu(message);
        }}
        onClick={handleClick}
      >
        {deleted ? (
          <span className={styles.deleted}>🚫 Xabar o'chirildi {meta}</span>
        ) : (
          <>
            {message.reply_to && (
              <button
                type="button"
                className={styles.quote}
                onClick={(e) => {
                  e.stopPropagation();
                  onQuoteClick(message.reply_to!.id);
                }}
              >
                <span className={styles.quoteWho}>{nameOf(message.reply_to.sender_user_id)}</span>
                <span className={styles.quoteText}>
                  {message.reply_to.deleted ? "O'chirilgan xabar" : message.reply_to.preview || '…'}
                </span>
              </button>
            )}
            <Body message={message} onOpenMedia={onOpenMedia} />
            {message.text && message.kind !== 'text' && (
              <div className={`${styles.text} ${styles.caption}`}>
                <RichText text={message.text} />
                {meta}
              </div>
            )}
            {message.kind === 'text' && (
              <div className={styles.text}>
                <RichText text={message.text ?? ''} />
                {meta}
              </div>
            )}
            {message.kind !== 'text' && !message.text && meta}
          </>
        )}
      </div>
    </div>
  );
}

export const MessageBubble = memo(MessageBubbleInner);

function RichText({ text }: { text: string }) {
  return (
    <>
      {linkify(text).map((part, i) =>
        part.href ? (
          <a
            key={i}
            href={part.href}
            target={part.href.startsWith('http') ? '_blank' : undefined}
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
          >
            {part.text}
          </a>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </>
  );
}

function Body({ message, onOpenMedia }: { message: UiMessage; onOpenMedia: (m: UiMessage) => void }) {
  const media = message.media;
  const local = message.local;

  switch (message.kind) {
    case 'photo':
    case 'video': {
      const src = media?.thumb_url ?? (message.kind === 'photo' ? media?.url : null) ?? local?.previewUrl ?? null;
      const ratio = media?.width && media?.height ? `${media.width} / ${media.height}` : '4 / 3';
      return (
        <button
          type="button"
          className={styles.mediaBox}
          style={{ aspectRatio: ratio }}
          onClick={(e) => {
            e.stopPropagation();
            if (!local) onOpenMedia(message);
          }}
        >
          {src && <img src={src} alt="" loading="lazy" decoding="async" />}
          {message.kind === 'video' && !local && <span className={styles.playIcon}>▶</span>}
          {message.kind === 'video' && media?.size_bytes != null && (
            <span className={styles.mediaBadge}>{formatBytes(media.size_bytes)}</span>
          )}
          {local?.status === 'sending' && (
            <span className={styles.progressRing}>{Math.round((local.progress ?? 0) * 100)}%</span>
          )}
        </button>
      );
    }
    case 'voice':
      return <VoicePlayer src={media?.url ?? local?.previewUrl ?? null} duration={message.duration_s} />;
    case 'document':
      return (
        <a
          className={styles.fileCard}
          href={media?.url ?? undefined}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => {
            e.stopPropagation();
            if (!media) e.preventDefault();
          }}
        >
          <span className={styles.fileIcon}>PDF</span>
          <span>
            <div className={styles.fileName}>{media?.name ?? 'Hujjat.pdf'}</div>
            <div className={styles.fileSub}>
              {local?.status === 'sending'
                ? `Yuklanmoqda… ${Math.round((local.progress ?? 0) * 100)}%`
                : media
                  ? formatBytes(media.size_bytes)
                  : ''}
            </div>
          </span>
        </a>
      );
    case 'location':
      if (message.lat == null || message.lon == null) return null;
      return (
        <a
          className={styles.fileCard}
          href={mapUrl(message.lat, message.lon)}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
        >
          <span className={`${styles.fileIcon} ${styles.locIcon}`}>📍</span>
          <span>
            <div className={styles.fileName}>Joylashuv</div>
            <div className={styles.fileSub}>
              {message.lat.toFixed(5)}, {message.lon.toFixed(5)} · xaritada ochish
            </div>
          </span>
        </a>
      );
    default:
      return null;
  }
}

/** Ovozli xabar pleyeri: bitta vaqtda bittasi o'ynaydi (yangisi boshlanganda
 *  boshqasi to'xtaydi — Telegram'dagi kabi). */
let currentAudio: HTMLAudioElement | null = null;

function VoicePlayer({ src, duration }: { src: string | null; duration: number | null }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);

  useEffect(() => {
    return () => {
      audioRef.current?.pause();
    };
  }, []);

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!src) return;
    let audio = audioRef.current;
    if (!audio) {
      audio = new Audio(src);
      audio.preload = 'auto';
      audio.ontimeupdate = () => setPosition(audio!.currentTime);
      audio.onended = () => {
        setPlaying(false);
        setPosition(0);
      };
      audio.onpause = () => setPlaying(false);
      audio.onplay = () => setPlaying(true);
      audioRef.current = audio;
    }
    if (audio.paused) {
      if (currentAudio && currentAudio !== audio) currentAudio.pause();
      currentAudio = audio;
      void audio.play().catch(() => setPlaying(false));
    } else {
      audio.pause();
    }
  };

  const total = duration ?? 0;
  const fraction = total > 0 ? Math.min(1, position / total) : 0;

  return (
    <div className={styles.voice}>
      <button type="button" className={styles.voicePlay} onClick={toggle} aria-label={playing ? 'Pauza' : 'Tinglash'}>
        {playing ? '❚❚' : '▶'}
      </button>
      <div className={styles.voiceTrack}>
        <div className={styles.voiceBar}>
          <div className={styles.voiceFill} style={{ width: `${fraction * 100}%` }} />
        </div>
        <span className={styles.voiceTime}>
          {playing || position > 0 ? formatDuration(position) : formatDuration(total)}
        </span>
      </div>
    </div>
  );
}
