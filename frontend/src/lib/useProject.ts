import { useQuery } from '@tanstack/react-query';

import { api, unwrap } from '../api/client';

export function useProject(key: string) {
  const project = useQuery({
    queryKey: ['project', key],
    queryFn: () => unwrap(api.GET('/api/v1/projects/by-key/{key}', { params: { path: { key } } })),
  });
  const id = project.data?.id;
  const fields = useQuery({
    queryKey: ['fields', id],
    enabled: !!id,
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/{project_id}/fields', { params: { path: { project_id: id! } } })),
  });
  const views = useQuery({
    queryKey: ['views', id],
    enabled: !!id,
    queryFn: () =>
      unwrap(api.GET('/api/v1/projects/{project_id}/views', { params: { path: { project_id: id! } } })),
  });
  const users = useQuery({ queryKey: ['users'], queryFn: () => unwrap(api.GET('/api/v1/users')) });
  return {
    project,
    fields: fields.data ?? [],
    views: views.data ?? [],
    users: users.data ?? [],
  };
}
