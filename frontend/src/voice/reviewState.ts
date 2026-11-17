/**
 * Voice step 4: lets the mic button and the trip wizard talk without a shared context.
 * - The wizard reports whether its review step is showing (the mic button sends screen "/trips/new#review").
 * - The voice "submit_review" action asks the wizard to press Proceed (it acts only on the review step).
 * - The wizard reports a created trip, so the voice draft can be cleared.
 */
let reviewShowing = false;

export const setReviewShowing = (showing: boolean) => { reviewShowing = showing; };
export const isReviewShowing = () => reviewShowing;

export const VOICE_SUBMIT_REVIEW = 'voyage:voice-submit-review';
export const TRIP_CREATED = 'voyage:trip-created';

export const requestSubmitReview = () => { window.dispatchEvent(new Event(VOICE_SUBMIT_REVIEW)); };
export const announceTripCreated = () => { window.dispatchEvent(new Event(TRIP_CREATED)); };
