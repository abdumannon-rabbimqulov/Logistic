import { useEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react';
import { CHAT_LIMITS, type ChatMediaKind } from '../../api/chat';
import styles from './Chat.module.css';
import { compressImage, formatBytes, formatDuration, videoPoster, voiceFileName } from './mediaUtils';
import { ReplyPreview } from './ReplyPreview';
import { VoiceRecorder } from './VoiceRecorder';

export interface MediaDraft {
  kind: ChatMediaKind;
  file: Blob;
  fileName: string;
  /** Lentada optimistik ko'rsatish uchun (blob: URL). */
  previewUrl: string | null;
  caption?: string;
  durationS?: number;
  thumb?: Blob | null;
  width?: number;
  height?: number;
}

interface Props {
  /** Yozib bo'lmasa — sabab; kompozer o'rniga shu matn ko'rsatiladi. */
  blockedReason: string | null;
  reply: { title: string; text: string } | null;
  onCancelReply: () => void;
  editing: { id: number; text: string } | null;
  onCancelEdit: () => void;
  onSendText: (text: string) => void;
  onSubmitEdit: (id: number, text: string) => void;
  onSendMedia: (draft: MediaDraft) => void;
  onSendLocation: () => void;
  onTyping: () => void;
  onError: (message: string) => void;
}

type Picker = 'camera' | 'gallery' | 'video' | 'document';

export function Composer({
  blockedReason,
  reply,
  onCancelReply,
  editing,
  onCancelEdit,
  onSendText,
  onSubmitEdit,
  onSendMedia,
  onSendLocation,
  onTyping,
  onError,
}: Props) {
  const [text, setText] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const [recording, setRecording] = useState(false);
  const [draft, setDraft] = useState<MediaDraft | null>(null);
  const [preparing, setPreparing] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const pickers = useRef<Record<Picker, HTMLInputElement | null>>({
    camera: null,
    gallery: null,
    video: null,
    document: null,
  });

  // Tahrirlash boshlanganda — eski matn maydonga; tugaganda tozalanadi.
  useEffect(() => {
    if (editing) {
      setText(editing.text);
      requestAnimationFrame(() => {
        const el = inputRef.current;
        if (!el) return;
        el.focus();
        // Kursor oxirida — aks holda ba'zi WebView'lar butun matnni belgilaydi va
        // birinchi bosilgan harf eski matnni almashtirib yuboradi.
        el.setSelectionRange(el.value.length, el.value.length);
      });
    } else {
      setText('');
    }
  }, [editing]);

  useEffect(() => {
    if (reply) inputRef.current?.focus();
  }, [reply]);

  // Maydon balandligi matnga moslashadi (140px gacha, keyin ichida aylanadi).
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
  }, [text]);

  if (blockedReason) {
    return <div className={styles.blocked}>{blockedReason}</div>;
  }

  const submit = () => {
    const value = text.trim();
    if (!value) return;
    if (editing) onSubmitEdit(editing.id, value);
    else onSendText(value);
    setText('');
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Kompyuterda Enter — yuborish, Shift+Enter — yangi qator. Telefonda klaviaturaning
    // Enter'i yangi qator (yuborish — tugma bilan), shuning uchun faqat aniq pointer'da.
    if (e.key === 'Enter' && !e.shiftKey && window.matchMedia('(pointer: fine)').matches) {
      e.preventDefault();
      submit();
    }
  };

  const openPicker = (p: Picker) => {
    setMenuOpen(false);
    pickers.current[p]?.click();
  };

  const onFile = async (kind: ChatMediaKind, e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // o'sha faylni qayta tanlash ham `change` bersin
    if (!file) return;
    setPreparing(true);
    try {
      if (kind === 'photo') {
        if (!file.type.startsWith('image/') || file.type === 'image/gif') {
          onError('Faqat rasm (JPEG, PNG, WEBP) yuborish mumkin');
          return;
        }
        const { blob, width, height } = await compressImage(file);
        if (blob.size > CHAT_LIMITS.photoBytes) {
          onError('Rasm juda katta (10 MB gacha)');
          return;
        }
        setDraft({
          kind,
          file: blob,
          fileName: blob === file ? file.name : 'photo.jpg',
          previewUrl: URL.createObjectURL(blob),
          width,
          height,
        });
      } else if (kind === 'video') {
        if (file.size > CHAT_LIMITS.videoBytes) {
          onError(`Video juda katta (${formatBytes(file.size)}). Ruxsat — 50 MB gacha.`);
          return;
        }
        const { poster, duration } = await videoPoster(file);
        setDraft({
          kind,
          file,
          fileName: file.name || 'video.mp4',
          previewUrl: URL.createObjectURL(file),
          thumb: poster,
          durationS: duration ?? undefined,
        });
      } else if (kind === 'document') {
        if (file.type && file.type !== 'application/pdf') {
          onError('Faqat PDF hujjat yuborish mumkin');
          return;
        }
        if (file.size > CHAT_LIMITS.documentBytes) {
          onError('Hujjat juda katta (20 MB gacha)');
          return;
        }
        setDraft({ kind, file, fileName: file.name || 'hujjat.pdf', previewUrl: null });
      }
    } finally {
      setPreparing(false);
    }
  };

  const closeDraft = () => {
    if (draft?.previewUrl) URL.revokeObjectURL(draft.previewUrl);
    setDraft(null);
  };

  const sendDraft = (caption: string) => {
    if (!draft) return;
    // previewUrl lentadagi optimistik xabarga o'tadi — u yerda bo'shatiladi.
    onSendMedia({ ...draft, caption: caption.trim() || undefined });
    setDraft(null);
  };

  const hasText = text.trim().length > 0;

  return (
    <div className={styles.composerWrap}>
      {editing ? (
        <ReplyPreview title="Tahrirlash" text={editing.text} onClose={onCancelEdit} />
      ) : (
        reply && <ReplyPreview title={reply.title} text={reply.text} onClose={onCancelReply} />
      )}

      <div className={styles.composer}>
        {!recording && (
          <>
            {!editing && (
              <button
                type="button"
                className={styles.iconBtn}
                onClick={() => setMenuOpen(true)}
                disabled={preparing}
                aria-label="Fayl biriktirish"
              >
                {preparing ? '…' : '📎'}
              </button>
            )}
            <textarea
              ref={inputRef}
              className={styles.input}
              value={text}
              rows={1}
              maxLength={4096}
              placeholder="Xabar"
              onChange={(e) => {
                setText(e.target.value);
                if (e.target.value) onTyping();
              }}
              onKeyDown={onKeyDown}
            />
          </>
        )}
        {hasText || editing ? (
          <button
            type="button"
            className={`${styles.iconBtn} ${styles.sendBtn}`}
            onClick={submit}
            disabled={!hasText}
            aria-label={editing ? 'Saqlash' : 'Yuborish'}
          >
            {editing ? '✓' : '➤'}
          </button>
        ) : (
          <VoiceRecorder
            onRecordingChange={setRecording}
            onError={onError}
            onRecorded={(blob, durationS, mime) =>
              onSendMedia({
                kind: 'voice',
                file: blob,
                fileName: voiceFileName(mime),
                previewUrl: URL.createObjectURL(blob),
                durationS,
              })
            }
          />
        )}
      </div>

      {/* Yashirin fayl tanlagichlar. `capture` — to'g'ridan-to'g'ri kamera. */}
      <input
        ref={(el) => {
          pickers.current.camera = el;
        }}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => void onFile('photo', e)}
      />
      <input
        ref={(el) => {
          pickers.current.gallery = el;
        }}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
        hidden
        onChange={(e) => void onFile('photo', e)}
      />
      <input
        ref={(el) => {
          pickers.current.video = el;
        }}
        type="file"
        accept="video/*"
        hidden
        onChange={(e) => void onFile('video', e)}
      />
      <input
        ref={(el) => {
          pickers.current.document = el;
        }}
        type="file"
        accept="application/pdf,.pdf"
        hidden
        onChange={(e) => void onFile('document', e)}
      />

      {menuOpen && (
        <div className={styles.backdrop} onClick={() => setMenuOpen(false)}>
          <div className={styles.sheet} onClick={(e) => e.stopPropagation()}>
            <SheetItem icon="📷" label="Kamera" onClick={() => openPicker('camera')} />
            <SheetItem icon="🖼" label="Galereyadan rasm" onClick={() => openPicker('gallery')} />
            <SheetItem icon="🎬" label="Video (50 MB gacha)" onClick={() => openPicker('video')} />
            <SheetItem icon="📄" label="Hujjat (PDF)" onClick={() => openPicker('document')} />
            <SheetItem
              icon="📍"
              label="Joylashuvni yuborish"
              onClick={() => {
                setMenuOpen(false);
                onSendLocation();
              }}
            />
          </div>
        </div>
      )}

      {draft && <DraftPreview draft={draft} onCancel={closeDraft} onSend={sendDraft} />}
    </div>
  );
}

function SheetItem({ icon, label, onClick, danger }: { icon: string; label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button type="button" className={`${styles.sheetItem} ${danger ? styles.sheetItemDanger : ''}`} onClick={onClick}>
      <span className={styles.sheetIcon}>{icon}</span>
      {label}
    </button>
  );
}

export { SheetItem };

/** Yuborishdan oldin ko'rish: rasm/video/hujjat va izoh (caption). */
function DraftPreview({
  draft,
  onCancel,
  onSend,
}: {
  draft: MediaDraft;
  onCancel: () => void;
  onSend: (caption: string) => void;
}) {
  const [caption, setCaption] = useState('');
  const title =
    draft.kind === 'photo' ? 'Rasm' : draft.kind === 'video' ? 'Video' : 'Hujjat';

  return (
    <div className={styles.draft} role="dialog" aria-modal="true">
      <div className={styles.draftHead}>
        <button type="button" className={styles.closeBtn} onClick={onCancel} aria-label="Bekor qilish">
          ✕
        </button>
        <span>
          {title} · {formatBytes(draft.file.size)}
          {draft.durationS ? ` · ${formatDuration(draft.durationS)}` : ''}
        </span>
        <span style={{ width: 36 }} />
      </div>
      <div className={styles.draftBody}>
        {draft.kind === 'photo' && draft.previewUrl && <img src={draft.previewUrl} alt="" />}
        {draft.kind === 'video' && draft.previewUrl && (
          <video src={draft.previewUrl} controls playsInline preload="metadata" />
        )}
        {draft.kind === 'document' && (
          <div className={styles.draftFile}>
            <span className={styles.fileIcon} style={{ width: 64, height: 64, fontSize: 16 }}>
              PDF
            </span>
            <span>{draft.fileName}</span>
          </div>
        )}
      </div>
      <div className={styles.draftFoot}>
        <textarea
          className={styles.input}
          rows={1}
          maxLength={1024}
          placeholder="Izoh qo'shing…"
          value={caption}
          onChange={(e) => setCaption(e.target.value)}
        />
        <button
          type="button"
          className={`${styles.iconBtn} ${styles.sendBtn}`}
          onClick={() => onSend(caption)}
          aria-label="Yuborish"
        >
          ➤
        </button>
      </div>
    </div>
  );
}
