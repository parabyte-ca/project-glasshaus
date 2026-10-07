import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { api, ApiError, unwrap } from '../api/client';
import { LoginPage } from '../pages/LoginPage';
import { AuthContext } from './useAuth';

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: ['me'],
    queryFn: () => unwrap(api.GET('/api/v1/users/me')),
    retry: (count, err) => !(err instanceof ApiError && err.status === 401) && count < 2,
    staleTime: 5 * 60_000,
  });
  const logout = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/auth/logout')),
    onSettled: () => queryClient.clear(),
  });

  if (me.isPending) {
    return (
      <p role="status" className="p-8 text-slate-600 dark:text-slate-400">
        Loading…
      </p>
    );
  }
  if (me.isError) {
    if (me.error instanceof ApiError && me.error.status === 401) return <LoginPage />;
    return (
      <p role="alert" className="p-8">
        Could not reach the server: {me.error.message}
      </p>
    );
  }
  return (
    <AuthContext.Provider value={{ user: me.data, logout: () => logout.mutate() }}>
      {children}
    </AuthContext.Provider>
  );
}
