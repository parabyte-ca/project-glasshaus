import { useQuery } from '@tanstack/react-query';

import { api, unwrap } from '../api/client';

/** The AI assistant's availability for this organization (cached; admins change it rarely). */
export function useAiStatus() {
  return useQuery({
    queryKey: ['ai-status'],
    queryFn: () => unwrap(api.GET('/api/v1/ai/status')),
    staleTime: 5 * 60_000,
  });
}
