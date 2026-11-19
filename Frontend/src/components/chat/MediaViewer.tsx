import { useEffect } from 'react';
import type { ChatMessage } from '../../api/chat';
import styles from './Chat.module.css';

interface Props {
  message: ChatMessage;
  onClose: () => void;
}

/** Rasm/videoni to'liq ekranda ko'rsatadi. Telegram'ning "Orqaga" tugmasi ham yopadi. */
export function MediaViewer({ message, onClose }: Props) {
  const media = message.media;

  useEffect(() => {
    const back = window.Telegram?.WebApp?.BackButton;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    back?.onClick(onClose);
    back?.show();
    return () => {
      window.removeEventListener('keydown', onKey);
      back?.offClick(onClose);
      back?.hide();
    };
  }, [onClose]);

  if (!media) return null;

  return (
    <div className={styles.viewer} onClick={onClose} role="dialog" aria-modal="true">
      <button type="button" className={styles.viewerClose} onClick={onClose} aria-label="Yopish">
        ✕
      </button>
      {message.kind === 'video' ? (
        <video
          src={media.url}
          poster={media.thumb_url ?? undefined}
          controls
          autoPlay
          playsInline
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <img src={media.url} alt="" onClick={(e) => e.stopPropagation()} />
      )}
      {message.text && <div className={styles.viewerCaption}>{message.text}</div>}
    </div>
  );
}
