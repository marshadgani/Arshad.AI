import { useCallback, useState } from 'react';

import { useAuth } from '../auth/AuthContext';

export interface SignOut {
  isSigningOut: boolean;
  signOut: () => Promise<void>;
}

// Sign-out is behaviour, not presentation: it owns the in-flight flag and the
// guarantee that the flag is cleared however logout() settles. Keeping it out
// of the Settings page means any other surface that grows a sign-out control
// gets the identical semantics instead of a second hand-rolled copy.
export function useSignOut(): SignOut {
  const { logout } = useAuth();
  const [isSigningOut, setIsSigningOut] = useState(false);

  const signOut = useCallback(async () => {
    setIsSigningOut(true);
    try {
      // logout() never rejects — AuthContext swallows the server-side
      // logout failure and always clears the local session — but `finally`
      // still covers the case where the caller stays mounted (e.g. the
      // redirect hasn't happened yet) so the control doesn't stay disabled.
      await logout();
    } finally {
      setIsSigningOut(false);
    }
  }, [logout]);

  return { isSigningOut, signOut };
}
