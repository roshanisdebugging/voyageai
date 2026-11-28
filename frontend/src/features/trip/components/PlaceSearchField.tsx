import React, { useEffect, useState } from 'react';
import { Search, MapPin, Loader2, AlertCircle, X } from 'lucide-react';
import type { DestinationReference } from '../types';
import { mapSearchErrorMessage } from '../../../utils/mapSearchError';
import { resolvePlace, suggestPlaces, SUGGEST_MIN_CHARS, type PlaceSuggestion } from '../../../services/placesApi';
import { GoogleMapsAttribution } from '../../../components/common/GoogleMapsAttribution';

/** India-only place search used for the destination and the starting city. */

export const isInIndia = (item: DestinationReference) => {
  const country = (item.country || '').toLowerCase();
  const lat = item.latitude;
  const lon = item.longitude;
  if (lat == null || lon == null) return false;
  return (country === 'india' || country === 'in' || !item.country)
    && lat >= 6.0 && lat <= 37.5 && lon >= 68.0 && lon <= 97.5;
};

export const placeSubtitle = (p: DestinationReference) =>
  [p.city, p.region, p.country].filter(Boolean).join(', ');

interface Props {
  id: string;
  label: string;
  placeholder: string;
  value: DestinationReference | null;
  onChange: (place: DestinationReference | null) => void;
  optional?: boolean;
}

export const PlaceSearchField: React.FC<Props> = ({ id, label, placeholder, value, onChange, optional }) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PlaceSuggestion[]>([]);
  const [picking, setPicking] = useState<string | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Suggestions while typing: autocomplete only (3+ characters); coordinates only for the one picked.
    if (query.trim().length < SUGGEST_MIN_CHARS) {
      setResults([]);
      setIsSearching(false);
      setError(null);
      return;
    }
    setIsSearching(true);
    setError(null);
    const timer = setTimeout(async () => {
      try {
        const data = await suggestPlaces(query);
        const list = Array.isArray(data) ? data : [];
        if (list.length === 0) {
          setError('No places found in India. Try a nearby city or a more specific name.');
        }
        setResults(list);
      } catch (err) {
        setError(mapSearchErrorMessage(err, "Couldn't search places. Check your connection and try again."));
        setResults([]);
      } finally {
        setIsSearching(false);
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [query]);

  return (
    <div className="space-y-2">
      <label htmlFor={value ? undefined : id} className="text-xs font-semibold text-(--itinerary-muted) block">
        {label} {optional && <span className="text-(--itinerary-muted) font-normal">(optional)</span>}
      </label>

      {value ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-[14px] border border-(--itinerary-accent) bg-(--itinerary-accent-surface) p-3.5">
          <div className="flex min-w-0 flex-1 items-center gap-2.5">
            <MapPin className="w-5 h-5 text-(--itinerary-accent) shrink-0" />
            <div className="min-w-0">
              <div className="font-extrabold text-sm text-(--color-text-primary) truncate">{value.name}</div>
              <div className="text-[11px] text-(--itinerary-muted) truncate">{placeSubtitle(value)}</div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => onChange(null)}
            className="flex min-h-11 shrink-0 items-center gap-1 rounded-[14px] border border-(--itinerary-control-border) bg-(--color-surface) px-2.5 text-xs font-bold hover:border-(--itinerary-accent)"
          >
            <X className="w-3.5 h-3.5" /> Change
          </button>
        </div>
      ) : (
        <>
          <div className="relative">
            <Search className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-(--itinerary-muted)" />
            <input
              id={id}
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder={placeholder}
              autoComplete="off"
              className="min-h-12 w-full rounded-[14px] border border-(--itinerary-control-border) bg-(--color-surface) py-3 pl-11 pr-9 text-[15px] text-(--color-text-primary)"
            />
            {isSearching && <Loader2 className="pointer-events-none absolute right-4 top-1/2 size-5 -translate-y-1/2 text-(--itinerary-accent) animate-spin" />}
          </div>

          {query.trim().length >= 2 && !isSearching && (
            <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
              {error ? (
                <div className="flex items-center gap-2 rounded-[14px] border border-(--itinerary-error) bg-(--itinerary-error-surface) p-3 text-xs text-(--itinerary-error)">
                  <AlertCircle className="w-4 h-4 shrink-0 text-(--itinerary-error)" />
                  <span>{error}</span>
                </div>
              ) : (
                results.map(result => (
                  <button
                    key={result.placeId}
                    type="button"
                    disabled={picking !== null}
                    onClick={async () => {
                      // One Place Details call, for this place only.
                      setPicking(result.placeId);
                      try {
                        const place = await resolvePlace(result.placeId);
                        if (place && isInIndia(place)) {
                          onChange({ ...place, name: place.name || result.name });
                          setQuery('');
                        } else {
                          setError('Cruiser supports places in India only. Pick a city or region in India.');
                        }
                      } catch (err) {
                        setError(mapSearchErrorMessage(err, "Couldn't search places. Check your connection and try again."));
                      } finally {
                        setPicking(null);
                      }
                    }}
                    className="flex w-full items-start gap-3 rounded-[14px] border border-(--itinerary-border) bg-(--color-surface-elevated) p-3 text-left transition-colors hover:border-(--itinerary-accent)"
                  >
                    <MapPin className="w-5 h-5 shrink-0 mt-0.5 text-(--itinerary-muted)" />
                    <div className="min-w-0 flex-1">
                      <div className="font-bold text-sm text-(--color-text-primary)">{result.name}</div>
                      <div className="text-[11px] text-(--itinerary-muted) truncate">{result.secondary}</div>
                    </div>
                  </button>
                ))
              )}
              {!error && results.length > 0 && (
                <div className="flex justify-end px-1"><GoogleMapsAttribution className="text-(--itinerary-muted)" /></div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};
