import { useState } from 'react';
import { ArrowRight, Compass, Plane, Wallet } from 'lucide-react';
import { nameProblem } from './bookingLogic';
import { submitOnEnter } from './bookingKeyboard';

const options = [
  { id: 'cheapest', title: 'Lowest fare', detail: 'Prioritize the lowest fare across airlines.', icon: Wallet },
  { id: 'specific', title: 'Specific airline', detail: 'Enter the airline you’d like to fly with.', icon: Plane },
  { id: 'any', title: 'No preference', detail: 'Leave the airline choice flexible.', icon: Compass },
] as const;

type Preference = typeof options[number]['id'];

export function AirlinePreference({ currentValue, busy, answer }: {
  currentValue?: string;
  busy: boolean;
  answer: (value: string) => void;
}) {
  const saved = currentValue && currentValue !== '-' ? currentValue : '';
  const [preference, setPreference] = useState<Preference>(() => {
    if (saved === 'any') return 'any';
    if (saved && saved !== 'cheapest') return 'specific';
    return 'cheapest';
  });
  const [airline, setAirline] = useState(preference === 'specific' ? saved : '');
  const [error, setError] = useState<string | null>(null);

  function advance() {
    if (busy) return;
    if (preference !== 'specific') {
      answer(preference);
      return;
    }
    const value = airline.trim();
    const problem = nameProblem(value, 40);
    if (problem) {
      setError(problem === 'script' ? 'Enter an airline name in English or Hindi.' : 'Enter a valid airline name.');
      return;
    }
    answer(value);
  }

  return (
    <form className="airline-preference" onSubmit={event => event.preventDefault()}
      onKeyDown={event => submitOnEnter(event, advance)}>
      <fieldset disabled={busy} className="airline-options">
        <legend className="sr-only">Airline preference</legend>
        {options.map(({ id, title, detail, icon: Icon }) => (
          <label className="airline-option" key={id}>
            <input type="radio" name="airline-preference" value={id} checked={preference === id}
              onChange={() => { setPreference(id); setError(null); }} />
            <Icon size={19} aria-hidden="true" />
            <span><strong>{title}</strong><small>{detail}</small></span>
          </label>
        ))}
      </fieldset>
      {preference === 'specific' && (
        <div className="airline-field">
          <label htmlFor="preferred-airline">Airline name</label>
          <input id="preferred-airline" maxLength={40} value={airline} placeholder="e.g. IndiGo"
            aria-invalid={Boolean(error)} aria-describedby={error ? 'preferred-airline-error' : undefined}
            onChange={event => { setAirline(event.target.value); setError(null); }} />
          {error && <p className="book-field-error" role="alert" id="preferred-airline-error">{error}</p>}
        </div>
      )}
      <button type="button" className="booking-primary" disabled={busy} onClick={advance}>
        Continue <ArrowRight size={17} aria-hidden="true" />
      </button>
    </form>
  );
}
