import React, { useState, useEffect, useRef } from 'react';
import { Portal } from '../common/Portal';
import { useLocation } from 'react-router-dom';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { isPastTrip } from '../../features/trip/tripRepository';
import { getApiBaseUrl, DEFAULT_FETCH_OPTIONS, getAuthHeaders } from '../../config/apiConfig';
import {
  MapPin, Navigation, Plus, ArrowUp,
  AlertTriangle, Compass, Clock, Check, Loader2,
  Sparkles, X
} from 'lucide-react';
import { FormattedText } from '../common/FormattedText';

// To load the font, add this to index.html:
// <link href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
// The system stack is the fallback if it isn't loaded.
const FONT_STACK = '"Hanken Grotesk", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif';


import { useDispatch, useSelector } from 'react-redux';
import { type RootState, type AppDispatch, fetchTourGuideHistory, appendGuideMessage } from '../../store';
import { useAuth } from '../../auth/AuthContext';

export interface ActionCardData {
  id: string;
  title: string;
  category?: string;
  location?: string;
  duration?: string;
  cost?: number;
  heads_up?: string;
}

export interface ChatMsg {
  id?: string;
  role: 'user' | 'assistant' | 'guide';
  sender?: 'user' | 'assistant';
  content: string;
  text?: string;
  mode?: 'local' | 'trip';
  card?: ActionCardData | null;
  chips?: string[];
  metadata?: {
    chips?: string[];
    card?: ActionCardData | null;
    error?: string;
  };
  created_at?: string;
}

const MAX_CHARS = 1000;
const WARNING_THRESHOLD = 900;

export const TourGuidePage: React.FC = () => {
  const dispatch = useDispatch();
  const location = useLocation();
  const { userLocation, userLocationName, activeContextMode, setActiveContextMode } = useApp();
  const { trips, currentTrip, refetchItinerary } = useTrip();

  const mode = activeContextMode;
  const setMode = setActiveContextMode;
  const [selectedTripId, setSelectedTripId] = useState<string | null>(null);

  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [addingCardId, setAddingCardId] = useState<string | null>(null);
  const [addedSuccessId, setAddedSuccessId] = useState<string | null>(null);
  const [showUpgradeModal, setShowUpgradeModal] = useState(false);

  const remaining = MAX_CHARS - input.length;
  const isExceeded = remaining < 0;
  const isNearLimit = input.length >= WARNING_THRESHOLD && !isExceeded;

  const chatBottomRef = useRef<HTMLDivElement>(null);

  const activeTrip = selectedTripId
    ? trips.find(t => t.id === selectedTripId) || currentTrip
    : currentTrip || trips.find(t => !isPastTrip(t)) || null;

  const destinationName = mode === 'trip'
    ? (activeTrip?.destination?.name || activeTrip?.title || 'Trip Destination')
    : null;

  const { authUser, userProfile } = useAuth();
  const userId = authUser?.id || userProfile?.userId;

  // 1. Redux Toolkit Slice: De-duplicated & Cached Tour Guide History
  const { history: historyData, messages: reduxMessages, loading: isHistoryLoading } = useSelector(
    (state: RootState) => state.tourGuide
  );
  const activeHistory = (historyData && historyData.length > 0) ? historyData : (reduxMessages || []);

  useEffect(() => {
    if (userId) {
      (dispatch as AppDispatch)(fetchTourGuideHistory());
    }
  }, [dispatch, userId]);

  // Sync RTK Query history into local messages when query resolves
  useEffect(() => {
    if (activeHistory && Array.isArray(activeHistory) && activeHistory.length > 0) {
      const parsedMsgs: ChatMsg[] = activeHistory.map((m: any) => {
        const meta = typeof m.metadata === 'string'
          ? (() => { try { return JSON.parse(m.metadata); } catch { return {}; } })()
          : (m.metadata || {});
        const role = m.role === 'assistant' || m.role === 'guide' || m.sender === 'assistant' ? 'assistant' : 'user';
        const content = m.text || m.content || meta.reply || '';
        const card = m.card || meta.card || null;
        const chips = m.chips || meta.chips || m.recommendations || [];

        return {
          id: m.id,
          role: role,
          sender: role,
          content: content,
          text: content,
          mode: m.mode,
          card: card,
          chips: chips,
          metadata: {
            ...meta,
            card: card,
            chips: chips
          }
        };
      });
      setMessages(parsedMsgs);
    } else if (!isHistoryLoading && (!activeHistory || activeHistory.length === 0) && messages.length === 0) {
      // Default Welcome Message if no history found
      setMessages([
        {
          id: 'welcome',
          role: 'assistant',
          content: "Namaste! I'm your Cruiser personal travel concierge. Ask me about authentic spots, street food, hacks, or itinerary planning.",
          metadata: {
            chips: ["Top food nearby", "What to see today?", "Hidden gems"]
          }
        }
      ]);
    }
  }, [activeHistory, isHistoryLoading]);

  // Sync router navigation state
  useEffect(() => {
    const navState = location.state as { mode?: 'local' | 'trip'; tripId?: string } | undefined;
    if (navState?.mode === 'trip' && navState?.tripId) {
      setMode('trip');
      setSelectedTripId(navState.tripId);
    } else if (currentTrip && !selectedTripId) {
      setSelectedTripId(currentTrip.id);
    }
  }, [location.state, currentTrip, selectedTripId]);

  // Auto-scroll chat to bottom
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleSend = async (queryText?: string) => {
    if (!queryText && isExceeded) {
      setShowUpgradeModal(true);
      return;
    }

    const textToSend = (queryText || input).trim();
    if (!textToSend || loading) return;

    if (!userId) {
      setMessages(prev => [
        ...prev,
        {
          id: `auth_err_${Date.now()}`,
          role: 'assistant',
          content: 'Please log in to chat with your AI travel guide and save your conversation.',
          metadata: { chips: ['Log in to continue'] }
        }
      ]);
      return;
    }

    // Extract recent 5 messages for client-driven context injection
    const recentHistory = messages.slice(-5).map(m => ({
      role: m.role === 'assistant' || m.role === 'guide' ? 'assistant' : 'user',
      content: m.content
    }));

    const userMsg: ChatMsg = {
      id: `u_${Date.now()}`,
      role: 'user',
      content: textToSend,
      mode: mode
    };

    setMessages(prev => [...prev, userMsg]);
    dispatch(appendGuideMessage(userMsg as any));
    if (!queryText) setInput('');
    setLoading(true);

    try {
      const baseUrl = getApiBaseUrl();
      const res = await fetch(`${baseUrl}/api/tour-guide/chat`, {
        ...DEFAULT_FETCH_OPTIONS,
        headers: getAuthHeaders(),
        method: 'POST',
        body: JSON.stringify({
          message: textToSend,
          mode: mode,
          trip_id: mode === 'trip' ? (activeTrip?.id || null) : null,
          destination_name: mode === 'trip' ? (destinationName || null) : null,
          user_location_name: mode === 'local' ? (userLocationName || null) : null,
          lat: mode === 'local' ? (userLocation?.[0] || null) : null,
          lng: mode === 'local' ? (userLocation?.[1] || null) : null,
          recent_history: recentHistory
        })
      });

      if (res.ok) {
        const data = await res.json();
        const assistantMsg: ChatMsg = {
          id: `g_${Date.now()}`,
          role: 'assistant',
          content: data.reply || "I'm here to help you explore!",
          mode: mode,
          metadata: {
            chips: data.chips || [],
            card: data.card || null,
            error: data.error
          }
        };
        setMessages(prev => [...prev, assistantMsg]);
        dispatch(appendGuideMessage(assistantMsg as any));
      } else {
        setMessages(prev => [
          ...prev,
          {
            id: `err_${Date.now()}`,
            role: 'assistant',
            content: "Connection thoda unstable hai dost. Ek baar query dobara bhej kar dekho!",
            metadata: {
              chips: ["Retry now", "Check connection"],
              error: "LLM_FAILURE"
            }
          }
        ]);
      }
    } catch (err) {
      console.error('[CONCIERGE CHAT ERROR]', err);
      setMessages(prev => [
        ...prev,
        {
          id: `err_${Date.now()}`,
          role: 'assistant',
          content: "Connection thoda unstable hai dost. Ek baar query dobara bhej kar dekho!",
          metadata: {
            chips: ["Retry now", "Check connection"],
            error: "LLM_FAILURE"
          }
        }
      ]);
    } finally {
      setLoading(false);
    }
  };

  // 3. Add Interactive Card to Day 1 Itinerary
  const handleAddToItinerary = async (card: ActionCardData) => {
    if (!card || !card.title || !activeTrip?.id) return;
    setAddingCardId(card.id);

    try {
      const baseUrl = getApiBaseUrl();
      const res = await fetch(`${baseUrl}/api/trips/itinerary/add`, {
        ...DEFAULT_FETCH_OPTIONS,
        headers: getAuthHeaders(),
        method: 'POST',
        body: JSON.stringify({
          trip_id: activeTrip.id,
          day_number: 1,
          item_id: card.id,
          title: card.title,
          location: card.location || destinationName || 'Location',
          tag: card.category || 'Sight',
          price: card.cost || 0
        })
      });

      if (res.ok) {
        setAddedSuccessId(card.id);
        setTimeout(() => setAddedSuccessId(null), 3000);
        if (refetchItinerary) {
          await refetchItinerary();
        }
      }
    } catch (err) {
      console.error('Failed to add activity to itinerary:', err);
    } finally {
      setAddingCardId(null);
    }
  };

  const lastIndex = messages.length - 1;

  return (
    <div
      className="flex flex-col h-[calc(100dvh-7.5rem)] sm:h-[calc(100dvh-6.5rem)] max-w-5xl w-full mx-auto bg-[#F4F5F2] text-[#16232B] overflow-hidden border border-[#DDE2DF] rounded-xl"
      style={{ fontFamily: FONT_STACK }}
    >
      {/* Header: who you're talking to, and what it's anchored to */}
      <header className="shrink-0 flex items-center justify-between gap-4 px-4 sm:px-6 py-3 bg-white border-b border-[#DDE2DF]">
        <div className="min-w-0">
          <h1 className="text-base font-semibold leading-tight">Jarvis</h1>
          <p className="text-xs text-[#5B6B73] truncate">
            {mode === 'trip'
              ? `Planning your trip to ${destinationName}`
              : userLocationName
                ? `Local tips near ${userLocationName}`
                : 'Local tips near you'}
          </p>
        </div>

        <div
          role="group"
          aria-label="Guide mode"
          className="flex shrink-0 rounded-lg bg-[#ECEEEA] p-0.5 text-xs font-medium"
        >
          <button
            type="button"
            onClick={() => setMode('local')}
            aria-pressed={mode === 'local'}
            title={userLocationName ? `Using your location: ${userLocationName}` : 'Using your live location'}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-md transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#16232B] ${
              mode === 'local' ? 'bg-[#16232B] text-white' : 'text-[#5B6B73] hover:text-[#16232B]'
            }`}
          >
            <MapPin className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
            <span className="max-w-[110px] truncate">{userLocationName || 'Near me'}</span>
          </button>
          {activeTrip && (
            <button
              type="button"
              onClick={() => setMode('trip')}
              aria-pressed={mode === 'trip'}
              className={`flex items-center gap-1.5 px-3 py-2 rounded-md transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#16232B] ${
                mode === 'trip' ? 'bg-[#16232B] text-white' : 'text-[#5B6B73] hover:text-[#16232B]'
              }`}
            >
              <Compass className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
              <span className="max-w-[110px] truncate">
                {activeTrip.destination?.name || activeTrip.title}
              </span>
            </button>
          )}
        </div>
      </header>

      {/* Conversation */}
      <div role="log" aria-live="polite" className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6 space-y-7">
          {messages.length === 0 && (
            <div className="py-16 max-w-md">
              <p className="text-base font-medium">Where to next?</p>
              <p className="mt-1 text-sm text-[#5B6B73]">
                Ask for local food, smart routes, or the places most visitors miss.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {['Best sunset view near me', 'Must-try street food', 'Hidden spots tourists miss'].map((starter) => (
                  <button
                    key={starter}
                    type="button"
                    onClick={() => handleSend(starter)}
                    className="px-3 py-2 rounded-lg border border-[#C9D0CC] bg-white text-xs font-medium hover:bg-[#ECEEEA] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#16232B]"
                  >
                    {starter}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => {
            const isUser = m.role === 'user' || m.sender === 'user';
            const textContent = m.text || m.content || '';
            const cardData = m.card || m.metadata?.card;
            const chipsList = m.chips || m.metadata?.chips;

            return (
              <div key={m.id || i} className={isUser ? 'flex justify-end' : ''}>
                {isUser ? (
                  <div className="max-w-[85%] sm:max-w-[75%] rounded-xl rounded-br-sm bg-[#16232B] text-white px-4 py-2.5 text-sm leading-relaxed">
                    <FormattedText content={textContent} isUserMessage />
                  </div>
                ) : (
                  <div className="max-w-[94%] sm:max-w-[85%]">
                    <div className="text-sm leading-relaxed text-[#16232B]">
                      <FormattedText content={textContent} isUserMessage={false} />
                    </div>

                    {/* Place card */}
                    {cardData && cardData.title && (
                      <div className="mt-4 rounded-xl bg-white border border-[#DDE2DF] overflow-hidden">
                        <div className="p-4">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="text-xs text-[#5B6B73]">{cardData.category || 'Sight'}</p>
                              <h4 className="mt-0.5 text-lg font-semibold leading-snug">{cardData.title}</h4>
                            </div>
                            {cardData.cost !== undefined && (
                              <p className="shrink-0 text-base font-semibold tabular-nums">₹{cardData.cost}</p>
                            )}
                          </div>

                          {(cardData.location || cardData.duration) && (
                            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[#5B6B73]">
                              {cardData.location && (
                                <span className="flex items-center gap-1.5">
                                  <MapPin className="w-3.5 h-3.5" aria-hidden="true" />
                                  {cardData.location}
                                </span>
                              )}
                              {cardData.duration && (
                                <span className="flex items-center gap-1.5">
                                  <Clock className="w-3.5 h-3.5" aria-hidden="true" />
                                  {cardData.duration}
                                </span>
                              )}
                            </div>
                          )}

                          {cardData.heads_up && (
                            <div className="mt-3 flex items-start gap-2 rounded-md border-l-4 border-[#D9930D] bg-[#FBF3DF] px-3 py-2 text-xs text-[#5A4210]">
                              <AlertTriangle className="w-4 h-4 shrink-0 mt-px text-[#B37A0A]" aria-hidden="true" />
                              <p>
                                <span className="font-semibold">Check before you go: </span>
                                {cardData.heads_up}
                              </p>
                            </div>
                          )}
                        </div>

                        {/* Perforated edge between details and actions */}
                        <div className="relative border-t border-dashed border-[#C9D0CC]" aria-hidden="true">
                          <span className="absolute -left-2 -top-2 w-4 h-4 rounded-full bg-[#F4F5F2] border border-[#DDE2DF]" />
                          <span className="absolute -right-2 -top-2 w-4 h-4 rounded-full bg-[#F4F5F2] border border-[#DDE2DF]" />
                        </div>

                        <div className="px-4 py-3 flex flex-wrap gap-2">
                          {mode === 'trip' && activeTrip && (
                            <button
                              type="button"
                              onClick={() => handleAddToItinerary(cardData)}
                              disabled={addingCardId === cardData.id}
                              className="flex-1 min-h-[40px] px-4 rounded-lg bg-[#16232B] text-white text-xs font-semibold flex items-center justify-center gap-1.5 hover:bg-[#22343F] disabled:opacity-60 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#16232B]"
                            >
                              {addingCardId === cardData.id ? (
                                <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" aria-label="Adding" />
                              ) : addedSuccessId === cardData.id ? (
                                <>
                                  <Check className="w-4 h-4" aria-hidden="true" /> Added to Day 1
                                </>
                              ) : (
                                <>
                                  <Plus className="w-4 h-4" aria-hidden="true" /> Add to Day 1
                                </>
                              )}
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() =>
                              window.open(
                                `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(cardData.title)}`,
                                '_blank'
                              )
                            }
                            className="min-h-[40px] px-4 rounded-lg border border-[#C9D0CC] bg-white text-xs font-semibold flex items-center justify-center gap-1.5 hover:bg-[#ECEEEA] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#16232B]"
                          >
                            <Navigation className="w-3.5 h-3.5" aria-hidden="true" /> Open in Maps
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Suggested replies: only on the latest message so old ones don't pile up */}
                    {i === lastIndex && chipsList && chipsList.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {chipsList.map((chip: string, idx: number) => (
                          <button
                            key={idx}
                            type="button"
                            onClick={() => handleSend(chip)}
                            className="px-3 py-1.5 rounded-lg border border-[#C9D0CC] bg-white text-xs font-medium hover:bg-[#ECEEEA] hover:border-[#16232B]/40 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#16232B]"
                          >
                            {chip}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {loading && (
            <div role="status" className="flex items-center gap-2.5 text-xs text-[#5B6B73]">
              <span className="flex gap-1" aria-hidden="true">
                {[0, 150, 300].map((delay) => (
                  <span
                    key={delay}
                    className="w-1.5 h-1.5 rounded-full bg-[#5B6B73] animate-pulse motion-reduce:animate-none"
                    style={{ animationDelay: `${delay}ms` }}
                  />
                ))}
              </span>
              Looking that up…
            </div>
          )}
          <div ref={chatBottomRef} />
        </div>
      </div>

      {/* Composer */}
      <div className="shrink-0 bg-white border-t border-[#DDE2DF]">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (isExceeded) {
              setShowUpgradeModal(true);
              return;
            }
            handleSend();
          }}
          className="max-w-3xl mx-auto flex items-center gap-2 p-3 sm:p-4"
        >
          <div className="relative flex-1">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && isExceeded) {
                  e.preventDefault();
                  setShowUpgradeModal(true);
                }
              }}
              aria-label="Message Jarvis"
              placeholder={
                mode === 'trip'
                  ? `Ask about ${destinationName}`
                  : `Ask about places in ${userLocationName || 'your area'}`
              }
              className={`w-full min-w-0 rounded-lg border bg-white pl-3.5 pr-14 py-2.5 text-sm placeholder:text-[#77858B] transition-all focus:outline-none ${
                isExceeded
                  ? 'border-rose-500 ring-1 ring-rose-500 focus:border-rose-500 focus:ring-rose-500'
                  : 'border-[#C9D0CC] focus:border-[#16232B] focus:ring-2 focus:ring-[#16232B]/15'
              }`}
            />
            {input.length > 0 && (
              <span
                aria-live="polite"
                className={`absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none select-none tabular-nums ${
                  isExceeded
                    ? 'text-rose-500 font-extrabold text-xs'
                    : isNearLimit
                    ? 'text-amber-500 font-semibold text-xs'
                    : 'text-slate-400 text-xs'
                }`}
              >
                {remaining}
              </span>
            )}
          </div>
          <button
            type="submit"
            onClick={(e) => {
              if (isExceeded) {
                e.preventDefault();
                setShowUpgradeModal(true);
              }
            }}
            disabled={!input.trim() || loading}
            aria-label="Send message"
            className={`w-10 h-10 shrink-0 rounded-lg flex items-center justify-center transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#16232B] ${
              isExceeded
                ? 'bg-rose-500 hover:bg-rose-600 text-white shadow-sm cursor-pointer'
                : 'bg-[#16232B] text-white hover:bg-[#22343F] disabled:bg-[#C9D0CC] disabled:cursor-not-allowed'
            }`}
          >
            <ArrowUp className="w-4 h-4" aria-hidden="true" />
          </button>
        </form>
      </div>

      {/* Upgrade Plan Warning Popup (Mock Modal) */}
      {showUpgradeModal && (
        <Portal>
          <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="upgrade-modal-title"
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[var(--z-modal)] flex items-center-safe justify-center p-4 animate-fadeIn overflow-y-auto"
          onClick={() => setShowUpgradeModal(false)}
        >
          <div
            className="bg-slate-900 border border-slate-800 p-6 max-w-md w-full shadow-2xl text-center rounded-2xl relative"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Close Button */}
            <button
              type="button"
              onClick={() => setShowUpgradeModal(false)}
              className="absolute top-4 right-4 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition-colors"
              aria-label="Close dialog"
            >
              <X className="w-4 h-4" />
            </button>

            {/* Icon / Badge */}
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs font-semibold mb-3">
              <Sparkles className="w-3.5 h-3.5 text-amber-400" />
              <span>⚡ Pro Feature</span>
            </div>

            {/* Headline */}
            <h3 id="upgrade-modal-title" className="text-xl font-bold text-white tracking-tight">
              Message Limit Exceeded
            </h3>

            {/* Body Copy */}
            <p className="mt-2.5 text-slate-300 text-sm leading-relaxed">
              Your message exceeds the 1,000 character limit for the standard tier. Please shorten your message or upgrade to Cruiser Pro for unlimited long-form travel planning and priority LLM routing.
            </p>

            {/* Character Overflow Info Box */}
            {isExceeded && (
              <div className="mt-4 py-2.5 px-3.5 rounded-lg bg-slate-800/80 border border-slate-700/60 flex items-center justify-between text-xs text-slate-300">
                <span>Message character count:</span>
                <span className="font-semibold text-rose-400 tabular-nums">
                  {input.length} / {MAX_CHARS} ({remaining} characters)
                </span>
              </div>
            )}

            {/* Actions */}
            <div className="mt-6 flex flex-col sm:flex-row items-center gap-3">
              <button
                type="button"
                onClick={() => setShowUpgradeModal(false)}
                className="w-full sm:flex-1 bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white font-medium px-4 py-2.5 rounded-lg hover:brightness-110 transition-all shadow-md text-sm cursor-pointer"
              >
                Upgrade Plan
              </button>
              <button
                type="button"
                onClick={() => setShowUpgradeModal(false)}
                className="w-full sm:flex-1 px-4 py-2.5 rounded-lg border border-slate-700 bg-slate-800/80 text-slate-300 hover:bg-slate-800 hover:text-white transition-colors text-sm font-medium cursor-pointer"
              >
                Edit Message
              </button>
            </div>
          </div>
        </div>
        </Portal>
      )}
    </div>
  );
};
