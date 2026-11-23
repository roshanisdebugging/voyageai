/**
 * The itinerary page's budget strip (pure; unit-tested in tests/budgetStrip.test.mjs).
 * Budget = trip.budget.targetAmount. Planned = the itinerary's known activity costs (estimatedCostInr; unknown costs
 * are not guessed). Spent = the trip's saved expenses (the same total the Expenses page shows).
 */

/** Same range as the server (trip_lifecycle MIN_BUDGET_INR / MAX_BUDGET_INR). */
export const MIN_BUDGET_INR = 1000;
export const MAX_BUDGET_INR = 10_000_000;

export interface BudgetStripModel {
  hasBudget: boolean;
  budget: number;
  /** null when no activity has a known cost */
  planned: number | null;
  spent: number;
  /** 0..100 of the budget */
  spentPct: number;
  plannedPct: number;
  overBudget: boolean;
  /** "Budget ₹25,000 · Planned ₹18,400 · Spent ₹3,200" (Planned left out when unknown) */
  label: string;
}

export const inr = (n: number): string => `₹${Math.round(n).toLocaleString('en-IN')}`;

const finite = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** Sum of the known activity costs, or null if none is known. */
export function plannedCost(itinerary: { days?: { activities?: { estimatedCostInr?: number | null }[] }[] } | null | undefined): number | null {
  let total = 0;
  let known = false;
  for (const d of itinerary?.days || []) {
    for (const a of d.activities || []) {
      const c = finite(a.estimatedCostInr);
      if (c !== null && c >= 0) { total += c; known = true; }
    }
  }
  return known ? total : null;
}

export function spentTotal(expenses: { amount?: number | null }[] | null | undefined): number {
  return (expenses || []).reduce((sum, e) => sum + (finite(e.amount) ?? 0), 0);
}

const pct = (part: number, whole: number) => (whole > 0 ? Math.min(100, Math.max(0, Math.round((part / whole) * 100))) : 0);

export function budgetStripModel(targetAmount: unknown, planned: number | null, spent: number): BudgetStripModel {
  const budget = finite(targetAmount) ?? 0;
  const hasBudget = budget > 0;
  const parts = [hasBudget ? `Budget ${inr(budget)}` : 'No budget set'];
  if (planned !== null) parts.push(`Planned ${inr(planned)}`);
  parts.push(`Spent ${inr(spent)}`);
  return {
    hasBudget,
    budget,
    planned,
    spent,
    spentPct: pct(spent, budget),
    plannedPct: pct(planned ?? 0, budget),
    overBudget: hasBudget && Math.max(spent, planned ?? 0) > budget,
    label: parts.join(' · '),
  };
}

/** The "Set budget" field: "25,000" / "25000" -> 25000; null with a reason when it can't be saved. */
export function parseBudgetInput(raw: string): { amount: number | null; error: string | null } {
  const cleaned = (raw || '').replace(/[₹,\s]/g, '');
  if (!cleaned) return { amount: null, error: 'Enter the budget in rupees.' };
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return { amount: null, error: 'Enter the budget in rupees.' };
  if (n < MIN_BUDGET_INR || n > MAX_BUDGET_INR) {
    return { amount: null, error: `Budget must be between ${inr(MIN_BUDGET_INR)} and ${inr(MAX_BUDGET_INR)}.` };
  }
  return { amount: Math.round(n), error: null };
}
