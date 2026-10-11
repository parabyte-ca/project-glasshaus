import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, unwrap, type Onboarding, type OnboardingUpdate } from '../api/client';

export const ONBOARDING_KEY = ['onboarding'] as const;

/** Checklist rows in display order; each ticks from the server-derived milestones. */
export const MILESTONES: { key: keyof Onboarding['milestones']; label: string }[] = [
  { key: 'created_work', label: 'Create your first project or task' },
  { key: 'added_collaborator', label: 'Assign a teammate or add a collaborator' },
  { key: 'set_due_date', label: 'Set a due date on a task' },
  { key: 'toured', label: 'Take the product tour' },
];

export function progressOf(state: Onboarding | undefined) {
  const done = MILESTONES.filter((m) => state?.milestones[m.key]).length;
  return { done, total: MILESTONES.length, percent: Math.round((done / MILESTONES.length) * 100) };
}

/**
 * The signed-in person's onboarding state (tour, checklist, dismissed tips), stored on their account
 * so it follows them across browsers. Updates apply optimistically.
 */
export function useOnboarding() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ONBOARDING_KEY,
    queryFn: () => unwrap(api.GET('/api/v1/users/me/onboarding')),
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: (body: OnboardingUpdate) => unwrap(api.PATCH('/api/v1/users/me/onboarding', { body })),
    onMutate: async (body) => {
      await queryClient.cancelQueries({ queryKey: ONBOARDING_KEY });
      const previous = queryClient.getQueryData<Onboarding>(ONBOARDING_KEY);
      if (previous && !body.reset) {
        queryClient.setQueryData<Onboarding>(ONBOARDING_KEY, {
          ...previous,
          tour: body.tour ?? previous.tour,
          checklist: body.checklist ?? previous.checklist,
          dismissed_tips: body.dismiss_tip
            ? [...previous.dismissed_tips.filter((t) => t !== body.dismiss_tip), body.dismiss_tip]
            : previous.dismissed_tips,
          milestones: {
            ...previous.milestones,
            toured: previous.milestones.toured || body.tour === 'completed',
          },
        });
      }
      return { previous };
    },
    onError: (_error, _body, context) => queryClient.setQueryData(ONBOARDING_KEY, context?.previous),
    onSuccess: (data) => queryClient.setQueryData(ONBOARDING_KEY, data),
  });
  return { state: query.data, update: mutation.mutate };
}
