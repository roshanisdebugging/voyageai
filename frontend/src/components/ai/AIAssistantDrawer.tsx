import React, { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { BottomSheet } from '../common/BottomSheet';
import { Send, Map, Utensils, Car, Wallet, Sparkles, CheckCircle2, AlertCircle, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { wsClient } from '../../services/wsClient';
import { FormattedText } from '../common/FormattedText';
import { getApiBaseUrl, DEFAULT_FETCH_OPTIONS } from '../../config/apiConfig';
import './AIAssistantDrawer.css';

interface SwapRecommendation {
  id: string;
  name: string;
  description: string;
  date: string;
  startTime: string;
  durationMinutes: number;
  locationName: string;
  latitude: number;
  longitude: number;
  estimatedCost: number;
  reason: string;
}

interface Message {
  id: string;
  role: 'user' | 'ai';
  text: string;
  actionType?: 'food' | 'cab' | 'map' | 'expense' | 'hotel';
  actionPayload?: string;
  recommendations?: SwapRecommendation[];
  refinementActions?: any[];
  currentActivityName?: string;
  activityId?: string;
  tripId?: string;
  dayId?: string;
  itineraryId?: string;
}

const suggestions = [
  { label: 'Find food near me', icon: Utensils, query: 'Recommend restaurants near my active destination' },
  { label: 'Book cab for transfer', icon: Car, query: 'Book a cab ride for my next activity' },
  { label: 'How much spent today?', icon: Wallet, query: 'How much have I spent today on my trip?' },
  { label: "What's nearby on map?", icon: Map, query: "Show me interesting places nearby on the map" },
];

export const AIAssistantSheet: React.FC = () => {
  const {
    isAiOpen, setIsAiOpen, aiPromptQuery, setAiPromptQuery,
    openCabModal, setIsFoodSheetOpen, swapContext, setSwapContext
  } = useApp();
  const { swapActivity, currentTrip, currentItinerary, executeRefinement } = useTrip();

  const navigate = useNavigate();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [applyingRefinement, setApplyingRefinement] = useState(false);

  // Swap Confirmation Modal state
  const [pendingSwap, setPendingSwap] = useState<{
    recommendation: SwapRecommendation;
    messageContext: Message;
  } | null>(null);
  const [swapSuccessMessage, setSwapSuccessMessage] = useState<string | null>(null);

  const drawerRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const confirmationRef = useRef<HTMLDialogElement>(null);
  const confirmationTitleId = useId();
  const isConfirmingSwap = isAiOpen && pendingSwap !== null;

  const closeDrawer = useCallback(() => {
    setIsAiOpen(false);
    setSwapContext(null);
    setPendingSwap(null);
  }, [setIsAiOpen, setSwapContext]);

  useEffect(() => {
    const drawer = drawerRef.current;
    const viewport = window.visualViewport;
    if (!isAiOpen || !drawer || !viewport) return;

    const clearKeyboardInset = () => {
      drawer.removeAttribute('data-keyboard-open');
      drawer.style.removeProperty('--concierge-keyboard-inset');
      drawer.style.removeProperty('--concierge-visual-height');
      drawer.style.removeProperty('--concierge-visual-top');
    };

    const syncViewport = () => {
      // Overlay keyboards resize the visual viewport while fixed elements stay in the layout viewport.
      if (viewport.scale !== 1 || window.innerHeight - viewport.height <= 80) {
        clearKeyboardInset();
        return;
      }

      const bottomInset = Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop);
      drawer.setAttribute('data-keyboard-open', '');
      drawer.style.setProperty('--concierge-keyboard-inset', `${Math.ceil(bottomInset)}px`);
      drawer.style.setProperty('--concierge-visual-height', `${Math.floor(viewport.height)}px`);
      drawer.style.setProperty('--concierge-visual-top', `${Math.max(0, viewport.offsetTop)}px`);
    };

    syncViewport();
    viewport.addEventListener('resize', syncViewport);
    viewport.addEventListener('scroll', syncViewport);
    window.addEventListener('resize', syncViewport);
    return () => {
      viewport.removeEventListener('resize', syncViewport);
      viewport.removeEventListener('scroll', syncViewport);
      window.removeEventListener('resize', syncViewport);
      clearKeyboardInset();
    };
  }, [isAiOpen]);

  useEffect(() => {
    const confirmation = confirmationRef.current;
    if (isConfirmingSwap && confirmation && !confirmation.open) confirmation.showModal();
    if (!isConfirmingSwap && confirmation?.open) confirmation.close();
  }, [isConfirmingSwap]);

  useEffect(() => {
    const transcript = scrollRef.current;
    if (isAiOpen && transcript) transcript.scrollTop = transcript.scrollHeight;
  }, [isAiOpen, messages, isSubmitting]);

  useEffect(() => {
    if (isAiOpen && aiPromptQuery) {
      handleSend(aiPromptQuery);
      setAiPromptQuery('');
    }
  }, [isAiOpen]);

  const handleApplyRefinement = async (targetTripId: string, actions: any[]) => {
    if (!targetTripId || !actions || actions.length === 0) return;
    setApplyingRefinement(true);
    try {
      await executeRefinement(targetTripId, actions);
      setSwapSuccessMessage(`Successfully applied ${actions.length} itinerary refinement(s) to PostgreSQL database!`);
      setMessages(prev => [...prev, {
        id: `ai-${Date.now()}`,
        role: 'ai',
        text: `Applied changes to your trip itinerary! Your trip updated successfully in PostgreSQL.`
      }]);
    } catch (err: any) {
      alert(err.message || 'Failed to apply itinerary refinements.');
    } finally {
      setApplyingRefinement(false);
    }
  };

  const [userCoords, setUserCoords] = useState<{ latitude: number; longitude: number } | null>(null);

  useEffect(() => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => setUserCoords({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }),
        () => {},
        { timeout: 5000 }
      );
    }
  }, []);

  const handleSend = async (textToSend?: string) => {
    const msg = textToSend || input;
    if (!msg.trim() || isSubmitting) return;

    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      text: msg
    };

    setMessages(prev => [...prev, userMsg]);
    if (!textToSend) setInput('');
    setIsSubmitting(true);

    try {
      const lowerMsg = msg.toLowerCase();
      const isRefinementRequest = currentTrip?.id && (
        lowerMsg.includes('replace') || lowerMsg.includes('remove') || lowerMsg.includes('make') || lowerMsg.includes('change') || lowerMsg.includes('move') || lowerMsg.includes('relax') || lowerMsg.includes('cheaper')
      );

      const isSwapPrompt = Boolean(swapContext) || msg.includes('Recommend alternatives for activity:') || lowerMsg.includes('swap');

      const payload = {
        message: msg,
        intent: isSwapPrompt ? 'SWAP_ACTIVITY' : (isRefinementRequest ? 'REFINE_ITINERARY' : 'CHAT'),
        tripId: swapContext?.tripId || currentTrip?.id,
        itineraryId: swapContext?.itineraryId || currentItinerary?.id,
        dayId: swapContext?.dayId,
        activityId: swapContext?.activityId,
        latitude: userCoords?.latitude,
        longitude: userCoords?.longitude,
        messages: messages.slice(-6).map(m => ({ role: m.role === 'user' ? 'user' : 'model', text: m.text }))
      };

      let data: any = null;
      try {
        data = await wsClient.sendRequest('ai:concierge', payload);
      } catch (wsErr) {
        console.warn('WebSocket Concierge request failed, trying HTTP fallback...', wsErr);
        try {
          const baseUrl = getApiBaseUrl();
          const res = await fetch(`${baseUrl}/api/ai/concierge`, {
            ...DEFAULT_FETCH_OPTIONS,
            method: 'POST',
            body: JSON.stringify(payload),
          });
          if (res.ok) {
            data = await res.json();
          }
        } catch (httpErr) {
          console.error('HTTP Concierge fallback failed:', httpErr);
        }
      }

      if (data) {
        if (data.type === 'activity_swap_recommendations') {
          const aiMsg: Message = {
            id: `ai-${Date.now()}`,
            role: 'ai',
            text: `Here are tailored alternatives for **${data.currentActivity?.title || swapContext?.activityName}**:`,
            recommendations: data.recommendations,
            currentActivityName: data.currentActivity?.title || swapContext?.activityName,
            activityId: data.activityId,
            tripId: data.tripId,
            dayId: data.dayId,
            itineraryId: data.itineraryId
          };
          setMessages(prev => [...prev, aiMsg]);
        } else if (data.type === 'refinement_actions') {
          const actions = data.actions || [];
          const aiMsg: Message = {
            id: `ai-${Date.now()}`,
            role: 'ai',
            text: `I've prepared ${actions.length} optimization action(s) for your trip **${currentTrip?.title || 'Itinerary'}**:\n\n` +
              actions.map((a: any, i: number) => `${i + 1}. **${a.action || a.type}**: ${a.reason || a.replacement?.name || 'Adjust activity timing and cost'}`).join('\n'),
            refinementActions: actions,
            tripId: currentTrip?.id
          };
          setMessages(prev => [...prev, aiMsg]);
        } else {
          const replyText = typeof data.reply === 'object'
            ? (data.reply?.reply || data.reply?.text || JSON.stringify(data.reply))
            : String(data.reply || "I am your Cruiser Assistant. How can I help with your journey?");
          const actionType = typeof data.reply === 'object' ? data.reply?.actionType : data.actionType;
          const actionPayload = typeof data.reply === 'object' ? data.reply?.actionPayload : data.actionPayload;

          const aiMsg: Message = {
            id: `ai-${Date.now()}`,
            role: 'ai',
            text: replyText,
            actionType,
            actionPayload
          };
          setMessages(prev => [...prev, aiMsg]);
        }
      } else {
        setMessages(prev => [...prev, {
          id: `ai-${Date.now()}`,
          role: 'ai',
          text: "I'm having trouble connecting to AI services right now. Please try again in a moment."
        }]);
      }
    } catch (err) {
      console.error("AI Concierge request error:", err);
      setMessages(prev => [...prev, {
        id: `ai-${Date.now()}`,
        role: 'ai',
        text: "Sorry, I encountered an error communicating with Gemini AI. Please ensure backend services are active."
      }]);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleConfirmSwap = async () => {
    if (!pendingSwap) return;
    const { recommendation, messageContext } = pendingSwap;
    const tripId = messageContext.tripId || swapContext?.tripId || currentTrip?.id;
    const activityId = messageContext.activityId || swapContext?.activityId;

    if (!tripId || !activityId) {
      alert('Missing trip or activity ID for swap.');
      setPendingSwap(null);
      return;
    }

    try {
      setIsSubmitting(true);
      await swapActivity(tripId, activityId, {
        itineraryId: messageContext.itineraryId || swapContext?.itineraryId,
        dayId: messageContext.dayId || swapContext?.dayId,
        replacement: {
          name: recommendation.name,
          description: recommendation.description,
          timeSlot: recommendation?.startTime ?? '10:00 AM',
          locationName: recommendation.locationName,
          latitude: recommendation.latitude,
          longitude: recommendation.longitude,
          estimatedCost: recommendation.estimatedCost
        }
      });

      setSwapSuccessMessage(`Activity successfully replaced with ${recommendation.name}`);
      setPendingSwap(null);
      setSwapContext(null);

      // Append success message in chat
      setMessages(prev => [
        ...prev,
        {
          id: `ai-swap-${Date.now()}`,
          role: 'ai',
          text: `**Activity Swapped!** Updated your itinerary to **${recommendation.name}** at ${recommendation?.startTime ?? '10:00 AM'} (₹${recommendation.estimatedCost ?? 0}). Budget and schedule updated.`
        }
      ]);

      setTimeout(() => setSwapSuccessMessage(null), 4000);
    } catch (err: any) {
      alert(err.message || 'Failed to complete activity swap');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleExecuteAction = (actionType?: string, payload?: string) => {
    setIsAiOpen(false);
    if (actionType === 'food') setIsFoodSheetOpen(true);
    if (actionType === 'cab') openCabModal(payload || 'Destination');
    if (actionType === 'map') navigate('/trip/map');
    if (actionType === 'expense') navigate('/trip/expenses');
  };

  return (
    <div ref={drawerRef} className="concierge-drawer">
      <BottomSheet
        isOpen={isAiOpen}
        onClose={closeDrawer}
        className="concierge-sheet"
        bodyClassName="concierge-sheet-body"
        maxHeight={`min(var(--concierge-preferred-height, ${messages.length > 0 ? '85dvh' : '58dvh'}), var(--concierge-available-height))`}
        title={swapContext ? `Swap Activity: ${swapContext.activityName}` : "Cruiser Concierge"}
      >
        <div className="flex min-h-0 w-full flex-col">
          {/* Success Banner */}
          {swapSuccessMessage && (
            <div role="status" className="concierge-success mx-4 mt-2 p-3 rounded-2xl text-[13px] font-bold flex shrink-0 items-center gap-2 animate-fadeIn">
              <CheckCircle2 className="w-4 h-4 shrink-0" aria-hidden="true" />
              <span>{swapSuccessMessage}</span>
            </div>
          )}

          {/* Messages Body */}
          <div ref={scrollRef} className="concierge-transcript min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3 space-y-3.5">
            {messages.length === 0 ? (
              <div className="space-y-4">
                <p className="text-sm text-[var(--color-text-secondary)] font-bold">How can I assist your trip right now?</p>
                <div className="space-y-2">
                  {suggestions.map(s => (
                    <button
                      key={s.label}
                      onClick={() => handleSend(s.query)}
                      className="concierge-suggestion w-full press-scale flex items-center gap-3 p-3.5 rounded-2xl border text-left transition-colors"
                    >
                      <s.icon className="w-4 h-4 text-[var(--color-primary)] shrink-0" aria-hidden="true" />
                      <span className="text-[13px] font-bold text-[var(--color-text-primary)]">{s.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map(msg => (
                <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`concierge-message wrap-anywhere p-3.5 rounded-2xl text-xs leading-relaxed space-y-2.5 ${
                    msg.role === 'user'
                      ? 'concierge-user-message font-bold rounded-br-none'
                      : 'bg-[var(--color-surface-elevated)] border border-[var(--color-border)] text-[var(--color-text-primary)] font-medium rounded-bl-none'
                  }`}>
                    <FormattedText content={msg.text} />

                    {/* Structured Activity Swap Recommendation Cards */}
                    {msg.role === 'ai' && msg.recommendations && msg.recommendations.length > 0 && (
                      <div className="space-y-2.5 pt-1">
                        {msg.recommendations.map(rec => {
                          const isSelected = pendingSwap?.recommendation.id === rec.id;
                          return (
                            <div
                              key={rec.id}
                              className={`p-3.5 rounded-2xl bg-[var(--color-surface)] border space-y-2 text-[var(--color-text-primary)] ${
                                isSelected
                                  ? 'border-[var(--color-primary)]'
                                  : 'border-[var(--color-border)]'
                              }`}
                            >
                              <div className="flex flex-wrap items-start justify-between gap-2">
                                <h5 className="font-extrabold text-sm text-[var(--color-text-primary)]">{rec.name}</h5>
                                <span className="concierge-recommendation-reason px-2 py-0.5 rounded-md text-[11px] font-extrabold">
                                  {rec.reason}
                                </span>
                              </div>

                              <p className="text-[13px] text-[var(--color-text-secondary)] font-medium">{rec.description}</p>

                              <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-[var(--color-text-primary)] pt-1 border-t border-[var(--color-border)]">
                                <span className="tabular-nums text-[var(--color-primary)] font-bold">
                                  {rec?.startTime ?? '10:00 AM'} • {rec?.durationMinutes ?? 60} mins
                                </span>
                                <span className="font-extrabold text-[var(--color-text-primary)]">
                                  {rec.estimatedCost ? `₹${rec.estimatedCost}` : 'Free'}
                                </span>
                              </div>

                              <button
                                type="button"
                                onClick={() => setPendingSwap({ recommendation: rec, messageContext: msg })}
                                className="concierge-primary-action w-full px-2 py-2.5 font-extrabold text-[13px] rounded-xl flex items-center justify-center gap-1.5 mt-1"
                                aria-haspopup="dialog"
                              >
                                <Sparkles className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                                <span>Select Recommendation</span>
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Refinement Actions Preview & Confirmation Button */}
                    {msg.role === 'ai' && msg.refinementActions && msg.refinementActions.length > 0 && (
                      <div className="pt-2">
                        <button
                          type="button"
                          disabled={applyingRefinement}
                          onClick={() => handleApplyRefinement(msg.tripId || currentTrip?.id || '', msg.refinementActions || [])}
                          className="concierge-primary-action w-full px-2 py-2.5 font-extrabold text-[13px] rounded-xl flex items-center justify-center gap-2"
                        >
                          <Sparkles className="w-4 h-4" />
                          <span>{applyingRefinement ? 'Applying Refinements...' : 'Apply Refinements to Itinerary'}</span>
                        </button>
                      </div>
                    )}

                    {/* Interactive Action Button embedded in standard AI Response */}
                    {msg.role === 'ai' && msg.actionType && (
                      <button
                        onClick={() => handleExecuteAction(msg.actionType, msg.actionPayload)}
                        className="concierge-primary-action text-[13px] py-2 px-3 mt-1.5 w-full flex items-center justify-center gap-1.5 rounded-2xl font-bold"
                      >
                        {msg.actionType === 'food' && <Utensils className="w-3.5 h-3.5" />}
                        {msg.actionType === 'cab' && <Car className="w-3.5 h-3.5" />}
                        {msg.actionType === 'map' && <Map className="w-3.5 h-3.5" />}
                        {msg.actionType === 'expense' && <Wallet className="w-3.5 h-3.5" />}
                        <span>Execute Action</span>
                      </button>
                    )}
                  </div>
                </div>
              ))
            )}
            {isSubmitting && !isConfirmingSwap && (
              <p role="status" className="concierge-loading text-[13px] text-[var(--color-text-secondary)]">Concierge is working…</p>
            )}
          </div>

          {/* Input Bar */}
          <form
            onSubmit={(e) => { e.preventDefault(); handleSend(); }}
            className="concierge-composer px-3.5 py-3 border-t border-[var(--color-border)] shrink-0 bg-[var(--color-surface)]"
          >
            <div className="flex items-center gap-2">
              <input
                type="text"
                aria-label="Message Cruiser Concierge"
                enterKeyHint="send"
                value={input}
                onChange={e => setInput(e.target.value)}
                placeholder={swapContext ? `Refine options (e.g. 'something cheaper')...` : "Ask Copilot anything..."}
                className="concierge-input w-full rounded-[14px] border px-3.5 py-3 text-base font-semibold text-[var(--color-text-primary)] placeholder:text-[var(--color-text-secondary)] min-w-0 flex-1"
              />
              <button
                type="submit"
                disabled={!input.trim() || isSubmitting}
                className="concierge-primary-action touch-target shrink-0 press-scale p-3 rounded-[14px] flex items-center justify-center"
                aria-label="Send message"
              >
                <Send className="w-4 h-4" aria-hidden="true" />
              </button>
            </div>
          </form>
        </div>
      </BottomSheet>

      <dialog
        ref={confirmationRef}
        className="concierge-confirmation space-y-4 wrap-anywhere"
        aria-labelledby={confirmationTitleId}
        onKeyDown={event => { if (event.key === 'Escape') event.stopPropagation(); }}
        onCancel={event => {
          event.preventDefault();
          if (!isSubmitting) setPendingSwap(null);
        }}
      >
        {pendingSwap && (
          <>
            <h4 id={confirmationTitleId} className="flex items-center gap-2 text-[var(--color-primary)] font-extrabold text-sm uppercase tracking-wider">
              <AlertCircle className="w-4 h-4 shrink-0" aria-hidden="true" />
              Replace Activity?
            </h4>

            <div className="space-y-3 py-2 border-y border-[var(--color-border)]">
              <div className="concierge-current-activity p-3 rounded-2xl text-xs">
                <span className="text-[11px] uppercase font-bold tracking-wider">Replacing Current Activity</span>
                <h5 className="font-bold text-[var(--color-text-primary)] text-sm mt-0.5">{pendingSwap.messageContext.currentActivityName || 'Current Activity'}</h5>
              </div>

              <div className="flex justify-center">
                <ArrowRight className="w-5 h-5 text-[var(--color-primary)] rotate-90" aria-hidden="true" />
              </div>

              <div className="p-3 rounded-2xl bg-[var(--color-surface-elevated)] border border-[var(--color-border)] text-xs">
                <span className="text-[11px] uppercase font-bold text-[var(--color-primary)] tracking-wider">With Selected Alternative</span>
                <h5 className="font-bold text-[var(--color-text-primary)] text-sm mt-0.5">{pendingSwap.recommendation.name}</h5>
                <p className="text-[var(--color-text-secondary)] mt-1 font-medium">{pendingSwap?.recommendation?.startTime ?? '10:00 AM'} • {pendingSwap?.recommendation?.estimatedCost ? `₹${pendingSwap.recommendation.estimatedCost}` : 'Free'}</p>
                <p className="text-[var(--color-text-secondary)] font-medium">{pendingSwap.recommendation.locationName}</p>
              </div>
            </div>

            <p className="text-xs text-[var(--color-text-secondary)] font-medium">This will update your persisted itinerary, schedule timing, and remaining trip budget.</p>

            <div className="flex items-center gap-3 pt-1">
              <button
                type="button"
                onClick={() => setPendingSwap(null)}
                disabled={isSubmitting}
                className="concierge-secondary-action flex-1 py-3 rounded-2xl font-bold text-xs border transition-colors"
              >
                Cancel
              </button>

              <button
                type="button"
                onClick={handleConfirmSwap}
                disabled={isSubmitting}
                className="concierge-primary-action flex-1 py-3 rounded-2xl font-extrabold text-xs"
              >
                {isSubmitting ? 'Updating...' : 'Confirm Swap'}
              </button>
            </div>
          </>
        )}
      </dialog>
    </div>
  );
};

export const AIAssistantDrawer = AIAssistantSheet;
