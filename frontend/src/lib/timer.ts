import { useQuery } from '@tanstack/react-query';

import { api, unwrap } from '../api/client';

export function useTimer() {
  return useQuery({
    queryKey: ['timer'],
    queryFn: () => unwrap(api.GET('/api/v1/timer')),
    refetchInterval: 60_000,
  });
}
