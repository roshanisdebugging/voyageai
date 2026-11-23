/**
 * Slim budget strip at the top of the itinerary: "Budget ₹25,000 · Planned ₹X · Spent ₹Y" with a progress bar.
 * No budget -> "No budget set" + "Set budget" (a number field, saved through TripContext.setTripBudget).
 * Voice changes (set_trip_budget, add_expense, smart actions) refresh the trip and expenses, so this updates by itself.
 */
import React, { useState } from 'react';
import { Pencil, Wallet } from 'lucide-react';
import { useTrip } from '../../features/trip/TripContext';
import { budgetStripModel, parseBudgetInput, plannedCost, spentTotal } from './budgetStrip';

export const TripBudgetStrip: React.FC = () => {
  const { currentTrip, currentItinerary, expenses, setTripBudget } = useTrip();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  if (!currentTrip) return null;

  const m = budgetStripModel(currentTrip.budget?.targetAmount, plannedCost(currentItinerary), spentTotal(expenses));

  const openEditor = () => {
    setValue(m.hasBudget ? String(Math.round(m.budget)) : '');
    setError(null);
    setEditing(true);
  };

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = parseBudgetInput(value);
    if (parsed.amount === null) { setError(parsed.error); return; }
    setSaving(true);
    setError(null);
    try {
      await setTripBudget(currentTrip.id, parsed.amount);
      setEditing(false);
    } catch (err) {
      // Not saved: say so and keep the field open.
      setError((err as Error)?.message || 'Could not save the budget. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const barColor = m.overBudget ? 'bg-rose-500' : 'bg-[var(--color-primary)]';
  return (
    <section aria-label="Trip budget"
      className="rounded-2xl bg-[var(--color-surface)] border border-[var(--color-border)] dark:border-zinc-700 px-4 py-3 space-y-2 shadow-xs">
      <div className="flex items-center justify-between gap-2">
        <p className="min-w-0 flex items-center gap-1.5 text-xs font-bold text-[var(--color-text-primary)] tabular-nums">
          <Wallet className="w-3.5 h-3.5 shrink-0 text-[var(--color-primary)]" aria-hidden="true" />
          <span className="wrap-anywhere">{m.label}</span>
        </p>
        {!editing && (
          <button type="button" onClick={openEditor}
            className="shrink-0 min-h-[32px] px-3 rounded-full border border-[var(--color-border)] dark:border-zinc-700 text-[11px] font-bold text-[var(--color-primary)] flex items-center gap-1 press-scale">
            {m.hasBudget ? <><Pencil className="w-3 h-3" aria-hidden="true" /> Change</> : 'Set budget'}
          </button>
        )}
      </div>

      {m.hasBudget && (
        <div className="relative h-1.5 rounded-full bg-[var(--color-surface-elevated)] dark:bg-zinc-800 overflow-hidden"
          role="progressbar" aria-label="Spent of budget" aria-valuemin={0} aria-valuemax={100} aria-valuenow={m.spentPct}>
          {m.planned !== null && (
            <div className="absolute inset-y-0 left-0 rounded-full bg-[var(--color-primary)]/25" style={{ width: `${m.plannedPct}%` }} />
          )}
          <div className={`absolute inset-y-0 left-0 rounded-full ${barColor}`} style={{ width: `${m.spentPct}%` }} />
        </div>
      )}
      {m.overBudget && (
        <p className="text-[10px] font-semibold text-rose-700 dark:text-rose-400">Over budget</p>
      )}

      {editing && (
        <form onSubmit={save} className="flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="trip-budget-input">Trip budget in rupees</label>
          <input id="trip-budget-input" type="text" inputMode="numeric" autoFocus value={value}
            onChange={(e) => setValue(e.target.value)} placeholder="e.g. 25000"
            className="flex-1 min-w-[120px] min-h-[40px] px-3 rounded-xl border border-[var(--color-border)] dark:border-zinc-700 bg-[var(--color-surface-elevated)] text-sm font-semibold text-[var(--color-text-primary)] tabular-nums" />
          <button type="submit" disabled={saving}
            className="min-h-[40px] px-4 rounded-xl bg-[var(--color-primary)] text-white dark:text-zinc-950 text-xs font-bold press-scale disabled:opacity-60">
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button type="button" onClick={() => setEditing(false)} disabled={saving}
            className="min-h-[40px] px-3 rounded-xl text-xs font-bold text-[var(--color-text-secondary)]">
            Cancel
          </button>
          {error && <p className="w-full text-[11px] font-semibold text-rose-700 dark:text-rose-400" role="alert">{error}</p>}
        </form>
      )}
    </section>
  );
};
