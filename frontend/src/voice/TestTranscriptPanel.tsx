import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Trash2 } from 'lucide-react';

/**
 * TEMPORARY, test phase only (voicefirst.md step 1). Shown when VITE_VOICE_TEST_TRANSCRIPT=true.
 * Lists what Groq Whisper heard. Kept in React state only: gone on reload, never saved.
 */
export interface PanelEntry {
  id: string;
  kind: 'transcript' | 'error';
  text: string;
  language?: string | null;
  durationMs?: number;
  groqMs?: number;
  roundTripMs?: number;
  truncated?: boolean;
  // Spoken reply (step 1b)
  replyText?: string;
  ttsMs?: number;
  totalMs?: number; // second tap -> reply starts playing
  at: number;
}

const seconds = (ms?: number) => (ms == null ? '–' : `${(ms / 1000).toFixed(1)} s`);

export const TestTranscriptPanel: React.FC<{ entries: PanelEntry[]; onClear: () => void }> = ({ entries, onClear }) => {
  const [open, setOpen] = useState(false); // collapsed by default: just the header pill
  const transcripts = entries.filter((e) => e.kind === 'transcript' && e.groqMs != null);
  const avgGroq = transcripts.length
    ? Math.round(transcripts.reduce((sum, e) => sum + (e.groqMs || 0), 0) / transcripts.length)
    : null;

  return (
    <section
      aria-label="Voice test transcripts"
      className="fixed z-[var(--z-floating)] left-3 w-[min(22rem,calc(100vw-24px))] lg:left-auto lg:right-4 lg:w-[22rem] rounded-2xl bg-white/95 dark:bg-zinc-900/95 backdrop-blur border border-amber-300 dark:border-amber-700 shadow-lg text-[#1F2522] dark:text-zinc-100"
      // At the top, under the header: away from the mic, Concierge and bottom nav, and (lg: right side) the sidebar.
      style={{ top: 'calc(var(--header-h) + var(--safe-top) + 8px)' }}
    >
      <header className="flex items-center justify-between gap-2 px-3 py-2 border-b border-amber-200 dark:border-amber-800">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-1.5 text-[11px] font-extrabold uppercase tracking-wider text-amber-800 dark:text-amber-300"
          aria-expanded={open}
        >
          {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
          Voice test · {transcripts.length} heard{avgGroq != null ? ` · Groq avg ${avgGroq} ms` : ''}
        </button>
        {entries.length > 0 && (
          <button type="button" onClick={onClear} aria-label="Clear transcripts" className="p-1 rounded-lg text-gray-500 hover:text-rose-600">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )}
      </header>

      {open && (
        <div className="max-h-[38vh] overflow-y-auto px-3 py-2 space-y-2">
          {entries.length === 0 ? (
            <p className="text-xs text-gray-500 dark:text-zinc-400 py-1">
              Tap the mic, speak, tap again. What Groq heard shows here. Nothing is saved by this panel.
            </p>
          ) : (
            entries.map((e) =>
              e.kind === 'error' ? (
                <p key={e.id} className="text-xs font-semibold text-rose-700 dark:text-rose-400">{e.text}</p>
              ) : (
                <div key={e.id} className="space-y-0.5">
                  <p className="text-sm font-medium leading-snug break-words">{e.text || <em className="text-gray-400">(nothing heard)</em>}</p>
                  <p className="text-[10px] text-gray-500 dark:text-zinc-400 font-mono">
                    {e.language || '?'} · clip {seconds(e.durationMs)}{e.truncated ? ' (cut at 30 s)' : ''} · Groq {e.groqMs} ms · transcript after {e.roundTripMs} ms
                  </p>
                  {e.replyText != null && (
                    <>
                      <p className="text-xs text-[#355F58] dark:text-emerald-400 leading-snug break-words">↳ {e.replyText}</p>
                      <p className="text-[10px] text-gray-500 dark:text-zinc-400 font-mono">
                        TTS {e.ttsMs} ms{e.totalMs != null ? ` · total ${e.totalMs} ms (tap → sound)` : ''}
                      </p>
                    </>
                  )}
                </div>
              )
            )
          )}
        </div>
      )}
    </section>
  );
};
