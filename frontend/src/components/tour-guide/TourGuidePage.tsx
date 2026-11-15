import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
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
import './guide-theme.css';

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

export const TourGuidePage: React.FC<{ micSlotRef?: React.Ref<HTMLDivElement> }> = ({ micSlotRef }) => {
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

  const conversationRef = useRef<HTMLDivElement>(null);
  const keepLatestVisible = useRef(true);

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
    const conversation = conversationRef.current;
    if (conversation) conversation.scrollTop = conversation.scrollHeight;
  }, [messages, loading]);

  useEffect(() => {
    const conversation = conversationRef.current;
    if (!conversation) return;
    const observer = new ResizeObserver(() => {
      if (keepLatestVisible.current) conversation.scrollTop = conversation.scrollHeight;
    });
    observer.observe(conversation);
    return () => observer.disconnect();
  }, []);

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
  const contextDescription = mode === 'trip'
    ? `Planning your trip to ${destinationName}`
    : userLocationName
      ? `Local tips near ${userLocationName}`
      : 'Local tips near you';

  return (
    <div
      className="guide-theme flex flex-1 min-h-0 flex-col max-w-5xl w-full mx-auto overflow-hidden border border-[var(--guide-border)] rounded-xl"
      style={{ fontFamily: FONT_STACK }}
    >
      {/* Header: who you're talking to, and what it's anchored to */}
      <header className="guide-chat-header shrink-0 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2.5 px-4 sm:px-6 py-3 bg-[var(--guide-panel)] border-b border-[var(--guide-border)]">
        <div className="min-w-0">
          <h1 className="text-base font-semibold leading-tight">Jarvis</h1>
          <p className="text-xs text-[var(--guide-muted)] line-clamp-2 sm:line-clamp-1 wrap-anywhere" title={contextDescription}>
            {contextDescription}
          </p>
        </div>

        <div
          role="group"
          aria-label="Guide mode"
          className="flex shrink-0 rounded-lg bg-[var(--guide-raised)] p-0.5 text-xs font-medium"
        >
          <button
            type="button"
            onClick={() => setMode('local')}
            aria-pressed={mode === 'local'}
            title={userLocationName ? `Using your location: ${userLocationName}` : 'Using your live location'}
            className="guide-mode flex min-h-11 items-center gap-1.5 px-2.5 rounded-md transition-colors"
          >
            <MapPin className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
            <span>Local</span>
          </button>
          {activeTrip && (
            <button
              type="button"
              onClick={() => setMode('trip')}
              aria-pressed={mode === 'trip'}
              title={activeTrip.destination?.name || activeTrip.title}
              className="guide-mode flex min-h-11 items-center gap-1.5 px-2.5 rounded-md transition-colors"
            >
              <Compass className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
              <span>Trip</span>
            </button>
          )}
        </div>
      </header>

      {/* Conversation */}
      <div
        ref={conversationRef}
        role="log"
        aria-label="Conversation with Jarvis"
        aria-live="polite"
        tabIndex={0}
        onScroll={(event) => {
          const { scrollHeight, clientHeight, scrollTop } = event.currentTarget;
          keepLatestVisible.current = scrollHeight - clientHeight - scrollTop < 48;
        }}
        className="flex-1 min-h-0 overflow-x-hidden overflow-y-auto overscroll-contain focus-visible:outline focus-visible:-outline-offset-2"
      >
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6 space-y-7">
          {messages.length === 0 && (
            <div className="py-16 max-w-md">
              <p className="text-base font-medium">Where to next?</p>
              <p className="mt-1 text-sm text-[var(--guide-muted)]">
                Ask for local food, smart routes, or the places most visitors miss.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {['Best sunset view near me', 'Must-try street food', 'Hidden spots tourists miss'].map((starter) => (
                  <button
                    key={starter}
                    type="button"
                    onClick={() => handleSend(starter)}
                    className="px-3 py-2 rounded-lg guide-control text-xs font-medium transition-colors"
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
                  <div className="max-w-[85%] sm:max-w-[75%] rounded-xl rounded-br-sm bg-[var(--guide-outgoing)] text-[var(--guide-outgoing-ink)] px-4 py-2.5 text-sm leading-relaxed">
                    <FormattedText content={textContent} />
                  </div>
                ) : (
                  <div className="max-w-[94%] sm:max-w-[85%]">
                    <div className="text-sm leading-relaxed">
                      <FormattedText content={textContent} />
                    </div>

                    {/* Place card */}
                    {cardData && cardData.title && (
                      <div className="mt-4 rounded-xl bg-[var(--guide-panel)] border border-[var(--guide-border)] overflow-hidden">
                        <div className="p-4">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="text-xs text-[var(--guide-muted)]">{cardData.category || 'Sight'}</p>
                              <h4 className="mt-0.5 text-lg font-semibold leading-snug">{cardData.title}</h4>
                            </div>
                            {cardData.cost !== undefined && (
                              <p className="shrink-0 text-base font-semibold tabular-nums">₹{cardData.cost}</p>
                            )}
                          </div>

                          {(cardData.location || cardData.duration) && (
                            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--guide-muted)]">
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
                            <div className="mt-3 flex items-start gap-2 rounded-md bg-[var(--guide-warning-panel)] px-3 py-2 text-xs text-[var(--guide-warning)]">
                              <AlertTriangle className="w-4 h-4 shrink-0 mt-px" aria-hidden="true" />
                              <p>
                                <span className="font-semibold">Check before you go: </span>
                                {cardData.heads_up}
                              </p>
                            </div>
                          )}
                        </div>

                        {/* Perforated edge between details and actions */}
                        <div className="relative border-t border-dashed border-[var(--guide-border)]" aria-hidden="true">
                          <span className="absolute -left-2 -top-2 w-4 h-4 rounded-full bg-[var(--guide-canvas)] border border-[var(--guide-border)]" />
                          <span className="absolute -right-2 -top-2 w-4 h-4 rounded-full bg-[var(--guide-canvas)] border border-[var(--guide-border)]" />
                        </div>

                        <div className="px-4 py-3 flex flex-wrap gap-2">
                          {mode === 'trip' && activeTrip && (
                            <button
                              type="button"
                              onClick={() => handleAddToItinerary(cardData)}
                              disabled={addingCardId === cardData.id}
                              className="flex-1 min-h-[40px] px-4 rounded-lg guide-control text-xs font-semibold flex items-center justify-center gap-1.5 disabled:opacity-60 transition-colors"
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
                            className="min-h-[40px] px-4 rounded-lg guide-control text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors"
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
                            className="px-3 py-1.5 rounded-lg guide-control text-xs font-medium transition-colors"
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
            <div role="status" className="flex items-center gap-2.5 text-xs text-[var(--guide-muted)]">
              <span className="flex gap-1" aria-hidden="true">
                {[0, 150, 300].map((delay) => (
                  <span
                    key={delay}
                    className="w-1.5 h-1.5 rounded-full bg-[var(--guide-muted)] animate-pulse motion-reduce:animate-none"
                    style={{ animationDelay: `${delay}ms` }}
                  />
                ))}
              </span>
              Looking that up…
            </div>
          )}
        </div>
      </div>

      {/* Composer */}
      <div className="shrink-0 bg-[var(--guide-panel)] border-t border-[var(--guide-border)]">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (isExceeded) {
              setShowUpgradeModal(true);
              return;
            }
            handleSend();
          }}
          className="guide-chat-composer max-w-3xl mx-auto flex items-center gap-2 p-3 sm:p-4"
        >
          <div className="relative min-w-0 flex-1">
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
              aria-invalid={isExceeded}
              className={`guide-input w-full min-w-0 min-h-11 rounded-lg pl-3.5 py-2.5 text-base transition-colors ${input.length > 0 ? 'pr-14' : 'pr-3.5'}`}
            />
            {input.length > 0 && (
              <span
                aria-live="polite"
                className={`absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none select-none tabular-nums ${
                  isExceeded
                    ? 'text-[var(--guide-error)] font-extrabold text-xs'
                    : isNearLimit
                    ? 'text-[var(--guide-warning)] font-semibold text-xs'
                    : 'text-[var(--guide-muted)] text-xs'
                }`}
              >
                {remaining}
              </span>
            )}
          </div>
          <div ref={micSlotRef} className="shrink-0 empty:hidden" />
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
            className={`guide-action guide-send size-11 shrink-0 rounded-lg flex items-center justify-center transition-colors ${isExceeded ? 'guide-send-over-limit' : ''}`}
          >
            <ArrowUp className="w-4 h-4" aria-hidden="true" />
          </button>
        </form>
      </div>

      {/* Upgrade Plan Warning Popup (Mock Modal) */}
      {showUpgradeModal && createPortal(
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="upgrade-modal-title"
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[9999] flex items-center justify-center p-4 animate-fadeIn"
          onClick={() => setShowUpgradeModal(false)}
        >
          <div
            className="guide-theme guide-limit-dialog p-6 max-w-md max-h-full overflow-y-auto w-full shadow-2xl text-center rounded-2xl relative"
            style={{ fontFamily: FONT_STACK }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Close Button */}
            <button
              type="button"
              onClick={() => setShowUpgradeModal(false)}
              className="absolute top-4 right-4 text-[var(--guide-muted)] hover:text-[var(--guide-ink)] p-1 rounded-lg hover:bg-[var(--guide-raised)] transition-colors"
              aria-label="Close dialog"
            >
              <X className="w-4 h-4" />
            </button>

            {/* Icon / Badge */}
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[var(--guide-warning-panel)] text-[var(--guide-warning)] text-xs font-semibold mb-3">
              <Sparkles className="w-3.5 h-3.5" />
              <span>Pro Feature</span>
            </div>

            {/* Headline */}
            <h3 id="upgrade-modal-title" className="text-xl font-bold tracking-tight">
              Message Limit Exceeded
            </h3>

            {/* Body Copy */}
            <p className="mt-2.5 text-[var(--guide-muted)] text-sm leading-relaxed">
              Your message exceeds the 1,000 character limit for the standard tier. Please shorten your message or upgrade to Cruiser Pro for unlimited long-form travel planning and priority LLM routing.
            </p>

            {/* Character Overflow Info Box */}
            {isExceeded && (
              <div className="mt-4 py-2.5 px-3.5 rounded-lg bg-[var(--guide-raised)] border border-[var(--guide-border)] flex flex-wrap items-center justify-between gap-1 text-xs text-[var(--guide-muted)]">
                <span>Message character count:</span>
                <span className="font-semibold text-[var(--guide-error)] tabular-nums">
                  {input.length} / {MAX_CHARS} ({remaining} characters)
                </span>
              </div>
            )}

            {/* Actions */}
            <div className="mt-6 flex flex-col sm:flex-row items-center gap-3">
              <button
                type="button"
                onClick={() => setShowUpgradeModal(false)}
                className="w-full sm:flex-1 guide-action font-medium px-4 py-2.5 rounded-lg transition-colors text-sm cursor-pointer"
              >
                Upgrade Plan
              </button>
              <button
                type="button"
                onClick={() => setShowUpgradeModal(false)}
                className="w-full sm:flex-1 px-4 py-2.5 rounded-lg guide-control transition-colors text-sm font-medium cursor-pointer"
              >
                Edit Message
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};
