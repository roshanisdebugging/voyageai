// The itinerary page's budget strip (src/components/itinerary/budgetStrip.ts). Run from frontend/: npm test
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadTs } from './tsload.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const B = await loadTs(join(here, '..', 'src', 'components', 'itinerary', 'budgetStrip.ts'));

let failed = 0, total = 0;
const check = (name, ok, detail = '') => { total++; if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? `  [${detail}]` : ''}`); };

const itin = { days: [{ activities: [{ estimatedCostInr: 500 }, { estimatedCostInr: null }, {}] }, { activities: [{ estimatedCostInr: 1200 }] }] };
check('planned = only the known activity costs', B.plannedCost(itin) === 1700, B.plannedCost(itin));
check('no known cost -> planned unknown (not 0)', B.plannedCost({ days: [{ activities: [{}] }] }) === null && B.plannedCost(null) === null);
check('spent = the saved expenses', B.spentTotal([{ amount: 300 }, { amount: 2900 }, { amount: null }]) === 3200);

let m = B.budgetStripModel(25000, 18400, 3200);
check('label "Budget ₹25,000 · Planned ₹18,400 · Spent ₹3,200"', m.label === 'Budget ₹25,000 · Planned ₹18,400 · Spent ₹3,200', m.label);
check('bar: spent 13%, planned 74%', m.spentPct === 13 && m.plannedPct === 74 && !m.overBudget, `${m.spentPct}/${m.plannedPct}`);
m = B.budgetStripModel(25000, null, 0);
check('planned unknown -> left out of the label', m.label === 'Budget ₹25,000 · Spent ₹0', m.label);
m = B.budgetStripModel(10000, 14000, 2000);
check('planned over the budget -> over budget, bar capped at 100', m.overBudget && m.plannedPct === 100);
m = B.budgetStripModel(null, 1200, 300);
check('no budget -> "No budget set", no bar values', !m.hasBudget && m.label.startsWith('No budget set') && m.spentPct === 0 && !m.overBudget, m.label);
check('budget 0 counts as none', !B.budgetStripModel(0, null, 0).hasBudget);

check('"25,000" -> 25000', B.parseBudgetInput('25,000').amount === 25000);
check('"₹ 40000" -> 40000', B.parseBudgetInput('₹ 40000').amount === 40000);
check('empty -> asks for rupees', B.parseBudgetInput('').amount === null && /rupees/.test(B.parseBudgetInput('').error));
check('500 -> refused with the range (same as the server)', B.parseBudgetInput('500').amount === null
  && B.parseBudgetInput('500').error === 'Budget must be between ₹1,000 and ₹1,00,00,000.', B.parseBudgetInput('500').error);
check('abc -> refused', B.parseBudgetInput('abc').amount === null);
check('range matches the server (1,000 .. 1,00,00,000)', B.MIN_BUDGET_INR === 1000 && B.MAX_BUDGET_INR === 10_000_000);

console.log(`\n${total - failed}/${total} passed`);
process.exit(failed ? 1 : 0);
