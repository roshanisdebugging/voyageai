import { useRef, useState } from 'react';
import { Clock3, Minus, Plus, Star } from 'lucide-react';

import { submitOnEnter } from './bookingKeyboard';
import type { TravelDetails, TravelDetailsAnswer } from './bookingApi';
import { nameProblem, NAME_MAX, NAME_MESSAGES } from './bookingLogic';

interface ControlProps {
  answer: (value: string) => void;
  busy: boolean;
  primaryClass: string;
  anyLabel: string;
  initialValue?: string;
}

function formatTimeEntry(value: string) {
  const digits = value.replace(/\D/g, '').slice(0, 4);
  return digits.length > 2 ? digits.slice(0, 2) + ':' + digits.slice(2) : digits;
}

export function DepartureWindow({ answer, busy, primaryClass, anyLabel, initialValue }: ControlProps) {
  const saved = initialValue?.match(/^(\d{2}:\d{2})–(\d{2}:\d{2})(?: \(\+1 day\))?$/);
  const [earliest, setEarliest] = useState(saved?.[1] ?? '08:00');
  const [latest, setLatest] = useState(saved?.[2] ?? '18:30');
  const clockTime = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
  const fromValid = clockTime.test(earliest);
  const toValid = clockTime.test(latest);
  const complete = fromValid && toValid && earliest !== latest;
  const invalid = (earliest.length === 5 && !fromValid) || (latest.length === 5 && !toValid);
  const overnight = complete && latest < earliest;

  const advance = () => { if (complete && !busy) answer(earliest + '–' + latest); };

  return (
    <form className="book-structured space-y-3" onSubmit={event => event.preventDefault()}
      onKeyDown={event => submitOnEnter(event, advance)}>
      <fieldset className="space-y-2">
        <legend className="book-field-label flex items-center gap-2"><Clock3 size={16} aria-hidden="true" /> Departure window</legend>
        <div className="book-time-fields">
          <label>Earliest departure<input type="text" inputMode="numeric" placeholder="08:00" value={earliest} onChange={event => setEarliest(formatTimeEntry(event.target.value))} aria-describedby="booking-time-hint" required /></label>
          <label>Latest departure<input type="text" inputMode="numeric" placeholder="18:30" value={latest} onChange={event => setLatest(formatTimeEntry(event.target.value))} aria-describedby="booking-time-hint" required /></label>
        </div>
        <p id="booking-time-hint" className="book-field-hint" aria-live="polite">
          {invalid ? 'Enter a 24-hour time from 00:00 to 23:59.'
            : overnight ? '24-hour time. The window ends the next day.'
            : fromValid && earliest === latest ? 'Choose two different times.'
            : '24-hour time (HH:MM), local to the departure city.'}
        </p>
      </fieldset>
      <button type="button" onClick={advance} className={primaryClass} disabled={!complete || busy}>Continue</button>
      <button type="button" className="book-text-action" onClick={() => answer('any')} disabled={busy}>{anyLabel}</button>
    </form>
  );
}

export function RoomCount({ answer, busy, primaryClass, anyLabel, initialValue }: ControlProps) {
  const saved = Number(initialValue);
  const [rooms, setRooms] = useState(Number.isInteger(saved) && saved >= 1 && saved <= 9 ? saved : 1);
  return (
    <div className="book-structured space-y-3">
      <div className="book-counter">
        <span className="book-field-label">Rooms</span>
        <button type="button" aria-label="Fewer rooms" disabled={rooms === 1 || busy} onClick={() => setRooms(rooms - 1)}><Minus size={18} /></button>
        <output aria-label="Room count">{rooms}</output>
        <button type="button" aria-label="More rooms" disabled={rooms === 9 || busy} onClick={() => setRooms(rooms + 1)}><Plus size={18} /></button>
      </div>
      <button type="button" className={primaryClass} onClick={() => answer(String(rooms))} disabled={busy}>Continue</button>
      <button type="button" className="book-text-action" onClick={() => answer('any')} disabled={busy}>{anyLabel}</button>
    </div>
  );
}

export function HotelRating({ answer, busy, primaryClass, initialValue }: ControlProps) {
  const saved = initialValue?.match(/^(?:rating:)([1-5])$/);
  const legacyRating = initialValue === '3star' ? 3 : initialValue === '4plus' ? 4 : 0;
  const [rating, setRating] = useState(saved ? Number(saved[1]) : legacyRating);
  const ratingLabel = rating === 0 ? 'Any rating' : rating + (rating === 1 ? ' star' : ' stars');
  const advance = () => { if (!busy) answer(rating ? `rating:${rating}` : 'any'); };
  return (
    <form className="book-structured space-y-4" onSubmit={event => event.preventDefault()}
      onKeyDown={event => submitOnEnter(event, advance)}>
      <div className="book-rating">
        <div className="book-rating-heading">
          <label htmlFor="book-hotel-rating" className="book-field-label">Preferred hotel rating</label>
          <output htmlFor="book-hotel-rating"><Star size={16} aria-hidden="true" />{ratingLabel}</output>
        </div>
        <input id="book-hotel-rating" type="range" min={0} max={5} step={1} value={rating}
          aria-valuetext={ratingLabel} aria-describedby="book-rating-hint"
          onChange={event => setRating(Number(event.target.value))} />
        <div className="book-rating-ticks" aria-hidden="true">{[0, 1, 2, 3, 4, 5].map(value => <span key={value}>{value}</span>)}</div>
        <p id="book-rating-hint" className="book-field-hint">0 means no rating preference.</p>
      </div>
      <button type="button" onClick={advance} className={primaryClass} disabled={busy}>Continue</button>
    </form>
  );
}

interface DetailsProps {
  details: TravelDetails;
  busy: boolean;
  primaryClass: string;
  answer: (values: TravelDetailsAnswer) => void;
}

export function TravelerDetails({ details, busy, primaryClass, answer }: DetailsProps) {
  const [error, setError] = useState<string | null>(null);
  const [confirmAge, setConfirmAge] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

  const advance = () => {
    const element = formRef.current;
    if (busy || !element?.reportValidity()) return;
    const form = new FormData(element);
    const travellers: TravelDetailsAnswer['travellers'] = [];
    let ageMismatch = false;
    for (const [index, traveler] of details.travelers.entries()) {
      const name = String(form.get('name-' + index)).trim();
      const age = String(form.get('age-' + index));
      const problem = nameProblem(name);
      if (problem) {
        setError('Traveler ' + (index + 1) + ' · ' + NAME_MESSAGES[problem]);
        return;
      }
      ageMismatch ||= (Number(age) < 18) !== traveler.isChild;
      travellers.push({ name, age });
    }
    const confirmAgeMismatch = form.get('confirm-age') === 'on';
    if (ageMismatch && !confirmAgeMismatch) {
      setConfirmAge(true);
      setError('Check and confirm the ages that differ from the trip’s adult and child categories.');
      return;
    }
    answer({ travellers, phone: String(form.get('phone')), confirmAgeMismatch });
  };
  return (
    <form ref={formRef} className="book-details-form space-y-4" onSubmit={event => event.preventDefault()}
      onKeyDown={event => submitOnEnter(event, advance)} onChange={event => {
        if (error) setError(null);
        if (event.target instanceof HTMLInputElement && event.target.name.startsWith('age-')) setConfirmAge(false);
      }}>
      <p className="book-field-hint">Add each traveler’s name and age, plus one contact number.</p>
      {details.travelers.map((traveler, index) => (
        <fieldset key={index} className="book-traveler-fields">
          <legend className="book-field-label">Traveler {index + 1} · {traveler.isChild ? 'Child' : 'Adult'}</legend>
          <label>Full name<input name={'name-' + index} defaultValue={traveler.name ?? ''} placeholder="Full name" maxLength={NAME_MAX} required /></label>
          <label>Age<input name={'age-' + index} type="number" inputMode="numeric" defaultValue={traveler.age ?? ''}
            placeholder="Years" min={0} max={110} step={1} required /></label>
        </fieldset>
      ))}
      <label className="book-contact-field">Mobile number<input name="phone" type="tel" inputMode="numeric" autoComplete="tel-national"
        defaultValue={details.phone ?? ''} placeholder="10-digit mobile number" maxLength={10} pattern="[6-9][0-9]{9}" required /></label>
      {confirmAge && (
        <label className="book-age-confirm">
          <input type="checkbox" name="confirm-age" /> I confirm the ages entered.
        </label>
      )}
      {error && <p role="alert" className="book-field-error">{error}</p>}
      <button type="button" onClick={advance} className={primaryClass} disabled={busy}>Review booking</button>
    </form>
  );
}
