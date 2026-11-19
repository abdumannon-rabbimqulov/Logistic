import styles from './Chat.module.css';

interface Props {
  /** "Javob: Haydovchi" yoki "Tahrirlash". */
  title: string;
  text: string;
  onClose: () => void;
}

/** Kompozer ustidagi panel: kimga javob berilayotgani yoki qaysi xabar tahrirlanayotgani. */
export function ReplyPreview({ title, text, onClose }: Props) {
  return (
    <div className={styles.replyBar}>
      <span className={styles.replyAccent} />
      <div className={styles.replyBody}>
        <div className={styles.replyTitle}>{title}</div>
        <div className={styles.replyText}>{text || '…'}</div>
      </div>
      <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Bekor qilish">
        ✕
      </button>
    </div>
  );
}
