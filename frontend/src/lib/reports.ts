import { useQuery } from '@tanstack/react-query';

import { api, unwrap } from '../api/client';

export function useReport(projectId: string, from?: string, to?: string) {
  return useQuery({
    queryKey: ['report', projectId, from, to],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/projects/{project_id}/report', {
          params: { path: { project_id: projectId }, query: { date_from: from, date_to: to } },
        }),
      ),
    enabled: !!projectId,
  });
}

export function useHealth(projectId: string) {
  return useQuery({
    queryKey: ['report', 'health', projectId],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/projects/{project_id}/health', { params: { path: { project_id: projectId } } }),
      ),
    enabled: !!projectId,
  });
}
