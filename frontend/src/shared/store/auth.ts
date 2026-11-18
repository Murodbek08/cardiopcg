import { create } from 'zustand';
import type { SessionUser } from '@/shared/api/types';

/**
 * Auth state lives ONLY in memory. The access token is never written to localStorage/sessionStorage
 * (XSS); the refresh token is an httpOnly cookie that JS cannot read.
 */
export type AuthStatus = 'unknown' | 'authenticated' | 'anonymous';
export type LogoutReason = 'logout' | 'session_expired' | 'token_reuse' | 'idle';

interface AuthState {
  status: AuthStatus;
  user: SessionUser | null;
  accessToken: string | null;
  logoutReason: LogoutReason | null;
  setSession: (user: SessionUser, accessToken: string) => void;
  setToken: (accessToken: string) => void;
  setUser: (user: SessionUser) => void;
  setAnonymous: () => void;
  logout: (reason?: LogoutReason) => void;
  clearReason: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  status: 'unknown',
  user: null,
  accessToken: null,
  logoutReason: null,
  setSession: (user, accessToken) => set({ user, accessToken, status: 'authenticated', logoutReason: null }),
  setToken: (accessToken) => set({ accessToken }),
  setUser: (user) => set({ user }),
  setAnonymous: () => set({ status: 'anonymous', user: null, accessToken: null }),
  logout: (reason = 'logout') => set({ status: 'anonymous', user: null, accessToken: null, logoutReason: reason }),
  clearReason: () => set({ logoutReason: null }),
}));

export const authSelectors = {
  role: (s: AuthState) => s.user?.role ?? null,
  isAuthed: (s: AuthState) => s.status === 'authenticated',
};
