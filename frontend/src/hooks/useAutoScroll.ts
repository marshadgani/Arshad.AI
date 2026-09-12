import { RefObject, useEffect } from 'react';

// Keeps a scroll container pinned to its bottom whenever `signals` change.
//
// `signals` are the values that indicate new content has been appended —
// the caller decides what those are, so this hook stays free of any
// knowledge of chat, messages or streams.
export function useAutoScroll(ref: RefObject<HTMLElement>, signals: unknown[]): void {
  useEffect(() => {
    ref.current?.scrollTo({
      top: ref.current.scrollHeight,
      behavior: 'smooth',
    });
    // `ref` is a stable ref object; only the content signals should re-run
    // this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, signals);
}
