import React, { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Bookmark, BookmarkCheck, Check, Clock, ExternalLink, Globe, Info, Loader2, MapPin, Phone, Plus } from 'lucide-react';
import { getApiBaseUrl, getDefaultFetchOptions } from '../../config/apiConfig';
import { checkPlaceSaved, removeSavedPlace, savePlace, type SavedPlaceItem } from '../../services/savedPlacesApi';
import { useToast } from '../common/UndoToast';
import { AddToItineraryModal } from '../itinerary/AddToItineraryModal';
import { usePlaceItineraryAdd } from '../itinerary/usePlaceItineraryAdd';
import { SAVED_PLACES_CHANGED, setScreenPlace } from '../../voice/screenPlace';

/** What the map card hands over in route state (shown at once, before any fetch). */
interface CardPlace {
  id: string;
  name: string;
  category?: string;
  distanceText?: string;
  address?: string;
  latitude?: number;
  longitude?: number;
  description?: string;
  price_approx?: string;
}

/** GET /api/places/details (Google Places). Missing fields are null / []. */
interface PlaceDetails {
  id: string;
  name: string;
  address: string;
  latitude: number | null;
  longitude: number | null;
  open_now: boolean | null;
  hours: string[];
  phone: string | null;
  website: string | null;
  maps_url: string | null;
  summary: string | null;
}

// Google place IDs only (same rule as the backend); the map's own "poi-..." IDs are never sent.
const GOOGLE_PLACE_ID = /^[A-Za-z0-9_-]{10,300}$/;
const isGooglePlaceId = (id: string) => GOOGLE_PLACE_ID.test(id) && !id.startsWith('poi-');

/** Today's line from Google's Monday-first weekday list. */
const todayIndex = () => (new Date().getDay() + 6) % 7;

const sentenceCase = (s?: string | null) => (s ? s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ').toLowerCase() : '');

const googleMapsUrl = (name: string, lat?: number | null, lng?: number | null, placeId?: string) => {
  const params = new URLSearchParams({ api: '1', query: lat != null && lng != null ? `${lat},${lng}` : name });
  if (placeId && isGooglePlaceId(placeId)) params.set('query_place_id', placeId);
  return `https://www.google.com/maps/search/?${params.toString()}`;
};

/** /details/:placeId — the map card's "Details". Card data first, then Google's details on top. */
export const PlaceDetailsPage: React.FC = () => {
  const { placeId = '' } = useParams();
  // A new place ID gets a fresh page (no details of the previous place).
  return <PlaceDetailsView key={placeId} placeId={placeId} />;
};

const PlaceDetailsView: React.FC<{ placeId: string }> = ({ placeId }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { showToast } = useToast();
  const card = ((location.state as { place?: CardPlace } | null)?.place) || null;
  const cardMatches = card && card.id === placeId ? card : null;
  const canFetch = isGooglePlaceId(placeId);

  const [details, setDetails] = useState<PlaceDetails | null>(null);
  const [loading, setLoading] = useState<boolean>(canFetch);
  const [failed, setFailed] = useState<boolean>(false);
  const [hoursOpen, setHoursOpen] = useState(false);
  const [isSaved, setIsSaved] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const savedTouchedRef = useRef(false); // once the user taps Save, a late initial check must not undo it
  const itineraryAdd = usePlaceItineraryAdd();

  useEffect(() => {
    if (!canFetch) return;
    let active = true;
    fetch(`${getApiBaseUrl()}/api/places/details?place_id=${encodeURIComponent(placeId)}`, getDefaultFetchOptions())
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as PlaceDetails;
      })
      .then((d) => { if (active) setDetails(d); })
      .catch(() => { if (active) setFailed(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [placeId, canFetch]);

  useEffect(() => {
    let active = true;
    checkPlaceSaved(placeId).then((saved) => { if (active && !savedTouchedRef.current) setIsSaved(saved); }).catch(() => {});
    return () => { active = false; };
  }, [placeId]);

  // Voice step 5: on this page, "yeh jagah save karo" means this place; a voice save/unsave re-checks the button.
  const voiceName = details?.name || cardMatches?.name || '';
  const voiceAddress = details?.address || cardMatches?.address || '';
  useEffect(() => {
    setScreenPlace(voiceName ? { place_id: placeId, name: voiceName, address: voiceAddress } : null);
    return () => setScreenPlace(null);
  }, [placeId, voiceName, voiceAddress]);
  useEffect(() => {
    const recheck = () => { checkPlaceSaved(placeId).then(setIsSaved).catch(() => {}); };
    window.addEventListener(SAVED_PLACES_CHANGED, recheck);
    return () => window.removeEventListener(SAVED_PLACES_CHANGED, recheck);
  }, [placeId]);

  const goBack = () => {
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
    if (idx > 0) navigate(-1);
    else navigate('/map');
  };

  // The card's data first, Google's details on top. Nothing is invented.
  const name = details?.name || cardMatches?.name || '';
  const address = details?.address || cardMatches?.address || '';
  const lat = details?.latitude ?? cardMatches?.latitude ?? null;
  const lng = details?.longitude ?? cardMatches?.longitude ?? null;
  const summary = details?.summary || cardMatches?.description || '';
  const hours = details?.hours || [];
  const today = hours[todayIndex()];

  if (!cardMatches && !details) {
    if (loading) {
      return (
        <div className="max-w-xl mx-auto p-4 space-y-3 animate-pulse" aria-busy="true" aria-label="Loading place">
          <div className="h-8 w-24 rounded-full bg-gray-200 dark:bg-zinc-800" />
          <div className="h-7 w-3/4 rounded bg-gray-200 dark:bg-zinc-800" />
          <div className="h-4 w-full rounded bg-gray-200 dark:bg-zinc-800" />
        </div>
      );
    }
    return (
      <div className="max-w-xl mx-auto p-6 text-center space-y-3">
        <h1 className="text-lg font-bold text-[#1F2522] dark:text-zinc-100">Place not found</h1>
        <p className="text-sm text-gray-500 dark:text-zinc-400">This place couldn't be loaded.</p>
        <button type="button" onClick={() => navigate('/map')}
          className="px-4 py-2 rounded-xl bg-[#1F5A3F] text-white text-sm font-semibold press-scale">Back to map</button>
      </div>
    );
  }

  const setSaved = async (save: boolean, withUndo: boolean) => {
    savedTouchedRef.current = true;
    setIsSaving(true);
    setIsSaved(save);
    try {
      if (save) {
        const item: SavedPlaceItem = {
          place_id: placeId, title: name, category: cardMatches?.category, location_name: address, location: address,
          coordinates: lat != null && lng != null ? [lat, lng] : undefined, description: summary || undefined,
        };
        await savePlace(item);
      } else {
        await removeSavedPlace(placeId);
      }
      if (withUndo) showToast({ message: save ? `Saved ${name}` : `Removed ${name} from saved places`, undo: () => { void setSaved(!save, false); } });
    } catch {
      setIsSaved(!save);
      showToast({ message: "Couldn't update saved places. Please try again." });
    } finally {
      setIsSaving(false);
    }
  };

  const added = itineraryAdd.addedPlaceDays.get(placeId);

  return (
    <div className="max-w-xl mx-auto px-4 pt-2 space-y-4 animate-fadeIn" style={{ paddingBottom: 'calc(var(--bottom-nav-h, 72px) + env(safe-area-inset-bottom, 0px) + 140px)' }}>
      <button type="button" onClick={goBack}
        className="min-h-[40px] px-3.5 rounded-full bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 text-xs font-semibold text-[#1F2522] dark:text-zinc-100 flex items-center gap-1.5 press-scale">
        <ArrowLeft className="w-4 h-4 text-[#1F5A3F] dark:text-emerald-400" aria-hidden="true" /> Back
      </button>

      <div className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          {cardMatches?.category && (
            <span className="px-2 py-0.5 rounded-md bg-[#1F5A3F]/10 dark:bg-emerald-950/60 text-[#1F5A3F] dark:text-emerald-400 border border-[#1F5A3F]/20 text-[10px] font-semibold uppercase">
              {sentenceCase(cardMatches.category)}
            </span>
          )}
          {cardMatches?.distanceText && <span className="text-[11px] font-medium text-gray-500 dark:text-zinc-400">{cardMatches.distanceText}</span>}
        </div>
        <h1 className="text-2xl font-extrabold text-[#1F2522] dark:text-zinc-100 leading-tight break-words">{name}</h1>
        {address && (
          <p className="text-sm text-gray-500 dark:text-zinc-400 flex items-start gap-1.5">
            <MapPin className="w-4 h-4 mt-0.5 shrink-0 text-[#1F5A3F] dark:text-emerald-400" aria-hidden="true" />
            <span>{address}</span>
          </p>
        )}
      </div>

      {loading && (
        <p className="text-xs text-gray-500 dark:text-zinc-400 flex items-center gap-1.5" role="status">
          <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" /> Loading more details…
        </p>
      )}
      {failed && (
        <p className="text-xs text-gray-500 dark:text-zinc-400 flex items-center gap-1.5" role="status">
          <Info className="w-3.5 h-3.5" aria-hidden="true" /> More details unavailable.
        </p>
      )}

      {(details?.open_now != null || today) && (
        <div className="rounded-2xl bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 p-3.5">
          <button type="button" onClick={() => setHoursOpen((o) => !o)} disabled={hours.length === 0}
            aria-expanded={hoursOpen} className="w-full flex items-start gap-2 text-left">
            <Clock className="w-4 h-4 mt-0.5 shrink-0 text-[#1F5A3F] dark:text-emerald-400" aria-hidden="true" />
            <span className="text-sm">
              {details?.open_now != null && (
                <span className={`font-bold ${details.open_now ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'}`}>
                  {details.open_now ? 'Open now' : 'Closed'}
                </span>
              )}
              {today && <span className="text-gray-600 dark:text-zinc-300">{details?.open_now != null ? ' · ' : ''}{today.replace(/^[A-Za-z]+:\s*/, '')}</span>}
            </span>
          </button>
          {hoursOpen && hours.length > 0 && (
            <ul className="mt-2 pl-6 space-y-0.5 text-xs text-gray-600 dark:text-zinc-400">
              {hours.map((h, i) => <li key={h} className={i === todayIndex() ? 'font-semibold text-[#1F2522] dark:text-zinc-100' : ''}>{h}</li>)}
            </ul>
          )}
        </div>
      )}

      {summary && <p className="text-sm text-gray-700 dark:text-zinc-300 leading-relaxed">{summary}</p>}

      {(details?.phone || details?.website) && (
        <div className="rounded-2xl bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 divide-y divide-gray-100 dark:divide-zinc-800">
          {details?.phone && (
            <a href={`tel:${details.phone.replace(/\s+/g, '')}`} className="flex items-center gap-2 p-3.5 text-sm text-[#1F2522] dark:text-zinc-100">
              <Phone className="w-4 h-4 text-[#1F5A3F] dark:text-emerald-400" aria-hidden="true" /> {details.phone}
            </a>
          )}
          {details?.website && (
            <a href={details.website} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 p-3.5 text-sm text-[#1F2522] dark:text-zinc-100 min-w-0">
              <Globe className="w-4 h-4 shrink-0 text-[#1F5A3F] dark:text-emerald-400" aria-hidden="true" />
              <span className="truncate">{details.website.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')}</span>
            </a>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <button type="button" onClick={() => itineraryAdd.open({ id: placeId, name, category: cardMatches?.category, address, price_approx: cardMatches?.price_approx })}
          className={`min-h-[44px] px-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-1.5 press-scale ${added
            ? 'bg-[#1F5A3F]/10 text-[#1F5A3F] dark:text-emerald-400 border border-[#1F5A3F]/30'
            : 'bg-[#1F5A3F] hover:bg-[#194B34] text-white'}`}>
          {added ? <><Check className="w-4 h-4" aria-hidden="true" /> Added to Day {added}</> : <><Plus className="w-4 h-4" aria-hidden="true" /> Add to Itinerary</>}
        </button>
        <button type="button" onClick={() => setSaved(!isSaved, true)} disabled={isSaving}
          aria-label={isSaved ? 'Remove from saved places' : 'Save place'}
          className="min-h-[44px] px-3 rounded-xl bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 text-sm font-semibold text-[#1F2522] dark:text-zinc-100 flex items-center justify-center gap-1.5 press-scale disabled:opacity-60">
          {isSaved ? <><BookmarkCheck className="w-4 h-4 text-[#1F5A3F] dark:text-emerald-400" aria-hidden="true" /> Saved</> : <><Bookmark className="w-4 h-4" aria-hidden="true" /> Save</>}
        </button>
        <a href={details?.maps_url || googleMapsUrl(name, lat, lng, placeId)} target="_blank" rel="noopener noreferrer"
          className="min-h-[44px] px-3 rounded-xl bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 text-sm font-semibold text-[#1F2522] dark:text-zinc-100 flex items-center justify-center gap-1.5 press-scale">
          <ExternalLink className="w-4 h-4 text-[#1F5A3F] dark:text-emerald-400" aria-hidden="true" /> Open in Google Maps
        </a>
      </div>

      <AddToItineraryModal {...itineraryAdd.modalProps} />
    </div>
  );
};

export default PlaceDetailsPage;
