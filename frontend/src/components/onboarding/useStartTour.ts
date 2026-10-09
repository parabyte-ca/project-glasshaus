import { useQuery } from '@tanstack/react-query';
import { useLocation, useNavigate } from 'react-router';

import { api, unwrap } from '../../api/client';

/**
 * Restart the product tour from anywhere: it runs on a project page, so go to the current project
 * (or the first one) with ?tour=1. Returns null when there is no project to tour yet.
 */
export function useStartTour(): (() => void) | null {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => unwrap(api.GET('/api/v1/projects')) });
  const current = /^\/projects\/([^/]+)$/.exec(pathname)?.[1];
  const key = current ?? projects.data?.[0]?.key;
  if (!key) return null;
  return () => navigate(`/projects/${key}?tour=1`);
}
