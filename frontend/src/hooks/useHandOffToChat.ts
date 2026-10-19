import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

import { CHAT_PATH } from '../routes/paths';

/** Input limit for text typed into a dashboard control that opens a chat. */
export const MAX_HANDOFF_CHARS = 500;

/**
 * Opens a new chat with text prefilled so the user reviews it and presses
 * Send. Nothing is ever sent from here. `handOff` returns false (and does not
 * navigate) when the text is blank, so the caller can tell the user.
 */
export function useHandOffToChat() {
  const navigate = useNavigate();

  const handOff = useCallback(
    (text: string): boolean => {
      const draft = text.trim();
      if (!draft) return false;
      navigate(CHAT_PATH, { state: { draft } });
      return true;
    },
    [navigate],
  );

  const openEmpty = useCallback(() => navigate(CHAT_PATH), [navigate]);

  return { handOff, openEmpty };
}
