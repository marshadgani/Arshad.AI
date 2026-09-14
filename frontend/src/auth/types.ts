// Kept apart from the implementation modules so a consumer needing only the
// vocabulary (the Login page needs OAuthProvider) doesn't import the React
// context to get it.

export type OAuthProvider = 'google' | 'github';

export type AuthUser = {
  id: string;
  email: string;
  name: string | null;
  avatarUrl: string | null;
};

export type AuthState = {
  token: string | null;
  user: AuthUser | null;
  isLoading: boolean;
  loginWith: (provider: OAuthProvider) => void;
  loginWithPassword: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  setTokenFromCallback: (token: string) => void;
};
