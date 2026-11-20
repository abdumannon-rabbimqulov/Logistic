import { useEffect, useRef, useState } from 'react';
import { searchAddress } from '../api/orders';
import type { GeocodeSuggestion } from '../types/api';
import { BottomSheetModal } from './BottomSheetModal';
import styles from './AddressSearchSheet.module.css';
import { PinIcon, SearchIcon } from './icons';

interface Props {
  title: string;
  onSelect: (suggestion: GeocodeSuggestion) => void;
  onClose: () => void;
  /** Berilsa — "Xaritadan tanlash" tugmasi ko'rsatiladi (markazdagi pin bilan tanlash). */
  onPickOnMap?: () => void;
}

export function AddressSearchSheet({ title, onSelect, onClose, onPickOnMap }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<GeocodeSuggestion[]>([]);
  const [searchState, setSearchState] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [retrySequence, setRetrySequence] = useState(0);
  const [composing, setComposing] = useState(false);
  const requestSequence = useRef(0);
  const immediateSearch = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (composing || query.trim().length < 3) {
      requestSequence.current += 1;
      setResults([]);
      setSearchState('idle');
      return;
    }

    const sequence = ++requestSequence.current;
    setSearchState('loading');
    const delay = immediateSearch.current ? 0 : 300;
    immediateSearch.current = false;
    const timer = window.setTimeout(async () => {
      try {
        const res = await searchAddress(query.trim());
        if (sequence !== requestSequence.current) return;
        setResults(res);
        setSearchState('success');
      } catch {
        if (sequence !== requestSequence.current) return;
        setResults([]);
        setSearchState('error');
      } finally {
        if (sequence === requestSequence.current) setSearchState((state) => state === 'loading' ? 'success' : state);
      }
    }, delay);
    return () => {
      window.clearTimeout(timer);
      requestSequence.current += 1;
    };
  }, [query, composing, retrySequence]);

  function clearSearch() {
    requestSequence.current += 1;
    setQuery('');
    setResults([]);
    setSearchState('idle');
    inputRef.current?.focus();
  }

  return (
    <BottomSheetModal title={title} onClose={onClose}>
      <div className={styles.searchField}>
        <input
          ref={inputRef}
          data-autofocus
          className={styles.input}
          aria-label="Manzilni qidirish"
          placeholder="Manzilni kiriting..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onCompositionStart={() => setComposing(true)}
          onCompositionEnd={() => setComposing(false)}
        />
        {query.length > 0 && (
          <button type="button" className={styles.clearButton} onClick={clearSearch} aria-label="Qidiruvni tozalash">×</button>
        )}
      </div>
      {onPickOnMap && (
        <button className={styles.pickOnMap} onClick={onPickOnMap}>
          <PinIcon />
          <span>Xaritadan tanlash</span>
        </button>
      )}
      {query.trim().length < 3 && <div className={styles.hint} role="status">Kamida 3 ta belgi kiriting</div>}
      {searchState === 'loading' && <div className={styles.hint} role="status">Manzillar qidirilmoqda…</div>}
      {searchState === 'error' && (
        <div className={styles.error} role="alert">
          Manzillar yuklanmadi.
          <button type="button" onClick={() => { immediateSearch.current = true; setRetrySequence((value) => value + 1); }}>Qayta urinish</button>
        </div>
      )}
      {searchState === 'success' && results.length === 0 && <div className={styles.hint}>Mos manzil topilmadi. Yozuvni tekshirib ko‘ring.</div>}
      <div className={styles.list}>
        {results.map((r, i) => (
          <button key={`${r.latitude}-${r.longitude}-${i}`} className={styles.item} onClick={() => onSelect(r)}>
            <SearchIcon />
            <span className={styles.itemText}>{r.address}</span>
          </button>
        ))}
      </div>
    </BottomSheetModal>
  );
}
