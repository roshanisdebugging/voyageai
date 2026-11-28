/**
 * The trip wizard's values as one object, and the two steps that move them (used by TripCreationWizard.tsx and, in
 * tests, by the same code the wizard runs):
 * - applyDraftToState: a TripDraft (voice prefill / an unfinished draft) -> the wizard's values
 * - buildCreateTripPayload: the wizard's values -> the createTrip payload sent on Proceed
 */
import type { TravelStyle } from '../../auth/types';
import { isPurposeType, purposePayload, type PurposeType } from './tripPurpose';
import type { CreateTripPayload, DestinationReference, TripDraft } from './types';

export interface WizardState {
  destination: DestinationReference | null;
  origin: DestinationReference | null;
  startDate: string;
  endDate: string;
  adults: number;
  children: number;
  styles: TravelStyle[];
  budgetAmount: number;
  planCardId: string | undefined;
  purposeType: PurposeType | null;
  purposeText: string;
  baseArea: DestinationReference | null;
}

const addDays = (dateStr: string, days: number) => {
  const base = new Date(`${dateStr}T00:00:00`);
  const valid = isNaN(base.getTime()) ? new Date() : base;
  valid.setDate(valid.getDate() + days);
  return `${valid.getFullYear()}-${String(valid.getMonth() + 1).padStart(2, '0')}-${String(valid.getDate()).padStart(2, '0')}`;
};

/** A draft's values over the current ones; a field the draft doesn't carry keeps its current value. */
export function applyDraftToState(state: WizardState, d: TripDraft, todayStr: string): WizardState {
  const next = { ...state };
  if (d.destination) next.destination = d.destination;
  if (d.origin !== undefined) next.origin = d.origin || null;
  if (d.startDate && d.startDate >= todayStr) {
    next.startDate = d.startDate;
    next.endDate = d.endDate && d.endDate >= d.startDate ? d.endDate : addDays(d.startDate, 3);
  }
  if (d.adultsCount != null) next.adults = Math.max(1, d.adultsCount);
  else if (d.travelersCount != null) next.adults = Math.max(1, d.travelersCount);
  if (d.childrenCount != null) next.children = Math.max(0, d.childrenCount);
  if (d.tripStyle) next.styles = d.tripStyle;
  if (d.customBudgetAmount) next.budgetAmount = d.customBudgetAmount;
  next.planCardId = d.planCardId;
  if (d.purposeType !== undefined) next.purposeType = isPurposeType(d.purposeType) ? d.purposeType : null;
  if (d.purposeText !== undefined) next.purposeText = d.purposeText || '';
  if (d.baseArea !== undefined) next.baseArea = d.baseArea || null;
  return next;
}

/** What Proceed sends (TripContext.createTrip -> trips:create / POST /api/trips -> create_trip_for_user). */
export function buildCreateTripPayload(s: WizardState & { destination: DestinationReference }): CreateTripPayload {
  return {
    destination: s.destination,
    origin: s.origin,
    startDate: s.startDate,
    endDate: s.endDate,
    adultsCount: s.adults,
    childrenCount: s.children,
    tripStyle: s.styles,
    budgetAmount: s.budgetAmount,
    ...(s.planCardId ? { planCardId: s.planCardId } : {}),
    ...(s.purposeType ? purposePayload(s.purposeType, s.purposeText, s.baseArea) : {}),
  };
}
