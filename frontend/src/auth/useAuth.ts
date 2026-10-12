import { createContext, useContext } from 'react';

import type { User } from '../api/client';

export interface AuthState {
  user: User;
  logout: () => void;
  /** True while the server cannot be reached and the app runs from this device's copy. */
  offline?: boolean;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>');
  return value;
}
