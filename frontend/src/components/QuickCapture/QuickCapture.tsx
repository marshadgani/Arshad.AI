import { type KeyboardEvent as ReactKeyboardEvent, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useHotkey } from '../../hooks/useHotkey';
import { useIsMobile } from '../../hooks/useBreakpoint';
import { CHAT_PATH, chatDraftState } from '../../routes';
import styles from './QuickCapture.module.css';

export interface QuickCaptureProps {
  /**
   * Suspends the Cmd/Ctrl+K shortcut while a TopBar popover owns focus, so
   * the shortcut can never yank focus out of an open dialog or menu. The
   * caller passes this because only it knows a popover is open; everything
   * else about the shortcut is this component's business.
   */
  hotkeyPaused?: boolean;
}

/**
 * The TopBar's capture bar: a single text field that hands whatever was
 * typed to the chat route as a prefilled draft.
 *
 * Owns its draft, its submit gesture and its keyboard shortcut. TopBar
 * previously held all three, which made the app's header — a layout
 * component rendered on every route — also the owner of transient input
 * state and a global window listener.
 */
export function QuickCapture({ hotkeyPaused = false }: QuickCaptureProps) {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const inputRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState('');

  // The capture bar is display:none below the mobile breakpoint, so the
  // shortcut would otherwise focus an invisible field.
  useHotkey(!isMobile && !hotkeyPaused, 'k', () => inputRef.current?.focus(), { meta: true });

  const handleKeyDown = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'Enter') return;
    const trimmed = draft.trim();
    if (!trimmed) return;
    setDraft('');
    navigate(CHAT_PATH, { state: chatDraftState(trimmed) });
  };

  return (
    <div className={styles.capture}>
      <span className={styles.captureIcon}>⌘</span>
      <input
        ref={inputRef}
        className={styles.captureInput}
        type="text"
        // Explicit, not placeholder-derived: a placeholder only supplies an
        // accessible name while the field is empty, so the name would
        // disappear the moment the user starts typing.
        aria-label="Quick capture"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder='Quick capture — type "log expense ₹420 lunch", "remind me 5 pm", or any thought…'
      />
      <span className={styles.kbd}>⌘ K</span>
    </div>
  );
}
