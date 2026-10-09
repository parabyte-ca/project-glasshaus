import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, type ReactNode } from 'react';

import { api, ApiError, unwrap } from '../api/client';
import { forgetOffline, rememberUser, rememberedUser } from '../lib/offline';
import { turnOff } from '../lib/push';
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
    mutationFn: async () => {
      // A shared device should stop getting this person's notifications and forget their tasks.
      await turnOff().catch(() => undefined);
      forgetOffline(me.data?.id);
      return unwrap(api.POST('/api/v1/auth/logout'));
    },
    onSettled: () => queryClient.clear(),
  });
  useEffect(() => {
    if (me.data) rememberUser(me.data);
  }, [me.data]);
  const cached = me.isSuccess ? null : rememberedUser();
  const unreachable =
    (me.isPending && me.fetchStatus === 'paused') || (me.isError && !(me.error instanceof ApiError));
  // Started without a connection: try the server again when the device is back online, and now and
  // then in case the 'online' event never comes (captive portals, a server that was down).
  const { refetch } = me;
  useEffect(() => {
    if (!unreachable) return;
    const retry = () => void refetch();
    window.addEventListener('online', retry);
    const timer = window.setInterval(retry, 30_000);
    return () => {
      window.removeEventListener('online', retry);
      window.clearInterval(timer);
    };
  }, [unreachable, refetch]);
  if (unreachable && cached) {
    return (
      <AuthContext.Provider value={{ user: cached, logout: () => logout.mutate(), offline: true }}>
        {children}
      </AuthContext.Provider>
    );
  }

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
