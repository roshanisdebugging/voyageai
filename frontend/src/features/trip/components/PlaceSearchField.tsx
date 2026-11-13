import React, { useEffect, useState } from 'react';
import { Search, MapPin, Loader2, AlertCircle, X } from 'lucide-react';
import type { DestinationReference } from '../types';
import { wsClient } from '../../../services/wsClient';

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
  const [results, setResults] = useState<DestinationReference[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([]);
      setIsSearching(false);
      setError(null);
      return;
    }
    setIsSearching(true);
    setError(null);
    const timer = setTimeout(async () => {
      try {
        const data: DestinationReference[] = await wsClient.sendRequest('places:search', { query: query.trim() });
        const india = Array.isArray(data) ? data.filter(isInIndia) : [];
        if (Array.isArray(data) && data.length > 0 && india.length === 0) {
          setError('Cruiser supports places in India only. Pick a city or region in India.');
        } else if (india.length === 0) {
          setError('No places found in India. Try a nearby city or a more specific name.');
        }
        setResults(india);
      } catch {
        setError("Couldn't search places. Check your connection and try again.");
        setResults([]);
      } finally {
        setIsSearching(false);
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [query]);

  return (
    <div className="space-y-2">
      <label htmlFor={id} className="text-xs font-semibold text-slate-400 block">
        {label} {optional && <span className="text-slate-500 font-normal">(optional)</span>}
      </label>

      {value ? (
        <div className="p-3.5 rounded-2xl bg-teal-500/15 border border-teal-500/50 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <MapPin className="w-5 h-5 text-teal-400 shrink-0" />
            <div className="min-w-0">
              <div className="font-extrabold text-sm text-white truncate">{value.name}</div>
              <div className="text-[11px] text-slate-300 truncate">{placeSubtitle(value)}</div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => onChange(null)}
            className="shrink-0 px-2.5 py-1.5 rounded-xl bg-slate-900 border border-slate-700 text-slate-300 text-[11px] font-bold flex items-center gap-1 hover:text-white"
          >
            <X className="w-3.5 h-3.5" /> Change
          </button>
        </div>
      ) : (
        <>
          <div className="relative">
            <Search className="w-5 h-5 absolute left-4 top-3.5 text-slate-400" />
            <input
              id={id}
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder={placeholder}
              autoComplete="off"
              className="w-full bg-slate-900 border border-slate-800 rounded-2xl py-3 pl-12 pr-10 text-slate-100 text-sm placeholder:text-slate-500 focus:outline-none focus:border-teal-500"
            />
            {isSearching && <Loader2 className="w-5 h-5 absolute right-4 top-3.5 text-teal-400 animate-spin" />}
          </div>

          {query.trim().length >= 2 && !isSearching && (
            <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
              {error ? (
                <div className="p-3 text-xs text-rose-300 bg-slate-900/60 border border-rose-900/50 rounded-2xl flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
                  <span>{error}</span>
                </div>
              ) : (
                results.map(result => (
                  <button
                    key={result.id || result.displayName || `${result.name}-${result.latitude}`}
                    type="button"
                    onClick={() => {
                      onChange(result);
                      setQuery('');
                    }}
                    className="w-full p-3 rounded-2xl border text-left flex items-start gap-3 bg-slate-900/90 border-slate-800 text-slate-300 hover:border-teal-500/40 active:scale-[0.98] transition-all"
                  >
                    <MapPin className="w-5 h-5 shrink-0 mt-0.5 text-slate-500" />
                    <div className="min-w-0 flex-1">
                      <div className="font-bold text-sm text-white">{result.name}</div>
                      <div className="text-[11px] text-slate-400 truncate">{placeSubtitle(result)}</div>
                    </div>
                  </button>
                ))
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};
