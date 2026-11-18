import { orderStatusMeta } from '../utils/orderStatus';
import styles from './OrderStatusBadge.module.css';

interface Props {
  status: string;
}

/** Rangli status belgisi: rang + nuqta + matn (faqat rangga tayanmaydi). */
export function OrderStatusBadge({ status }: Props) {
  const meta = orderStatusMeta(status);
  return (
    <span className={`${styles.badge} ${styles[meta.tone]}`}>
      <span className={styles.dot} aria-hidden="true" />
      {meta.label}
    </span>
  );
}
