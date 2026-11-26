import type { PlanCardMeta, Trip } from '../../features/trip/types';

/** The checked plan (pilgrimage card) a trip was made from, or null for every other trip. */
export const planCardOf = (trip: Trip | null | undefined): PlanCardMeta | null => {
  const meta = (trip?.preferencesSnapshot as { planCard?: PlanCardMeta } | undefined)?.planCard;
  return meta && typeof meta.id === 'string' ? meta : null;
};
