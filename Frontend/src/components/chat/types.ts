import type { ChatMessage } from '../../api/chat';

/** Lentadagi xabar: serverdan kelgan yoki hali yuborilayotgan (optimistik). */
export interface UiMessage extends ChatMessage {
  local?: {
    status: 'sending' | 'failed';
    /** Yuklash jarayoni 0..1 (media uchun). */
    progress?: number;
    /** Yuklanayotgan faylning lokal ko'rinishi (blob: URL). */
    previewUrl?: string;
    error?: string;
  };
}

export type BubbleAction = 'reply' | 'copy' | 'edit' | 'delete' | 'retry' | 'discard';
