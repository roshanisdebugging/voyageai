import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import {
  Wallet, ArrowLeft, Plus, PieChart, Sparkles, Car, Building2, UtensilsCrossed, ShoppingBag, Compass, CreditCard, X
} from 'lucide-react';
import type { Expense } from '../../types';

export const ExpensesPage: React.FC = () => {
  const navigate = useNavigate();
  const { activeTrip, expenses: appExpenses, addExpense: addAppExpense, setTripView, setActiveTab, openAiAssistant } = useApp();
  const { currentTrip, expenses: tripExpenses, addExpense: addTripExpense } = useTrip();

  const activeDestName = (currentTrip?.destination?.name) || (typeof activeTrip?.destination === 'string' ? activeTrip.destination : '') || 'Kerala';

  const [showAddModal, setShowAddModal] = useState(false);
  const [title, setTitle] = useState('');
  const [amount, setAmount] = useState('');
  const [category, setCategory] = useState<Expense['category']>('Food');
  const [isSplit, setIsSplit] = useState(true);

  // Combine persisted trip expenses with local app expenses
  const combinedExpenses: Expense[] = [
    ...tripExpenses.map(e => ({
      id: e.id,
      title: e.title,
      amount: e.amount,
      category: e.category,
      date: 'Today',
      paidBy: e.paidBy || 'Me',
      isSplit: e.isSplit,
    })),
    ...appExpenses.filter(ae => !tripExpenses.some(te => te.id === ae.id)),
  ];

  const totalSpent = combinedExpenses.reduce((acc, e) => acc + e.amount, 0);
  // The trip's real budget amount; 0 when the trip has none.
  const targetBudget = currentTrip?.budget?.targetAmount ?? 0;
  const budgetRemaining = Math.max(0, targetBudget - totalSpent);
  const progressPct = targetBudget > 0 ? Math.min(100, Math.round((totalSpent / targetBudget) * 100)) : 0;

  // Category totals breakdown
  const categoryTotals: Record<string, number> = {
    Food: 0,
    Transport: 0,
    Hotel: 0,
    Activities: 0,
    Shopping: 0,
    Other: 0
  };

  combinedExpenses.forEach(exp => {
    categoryTotals[exp.category] = (categoryTotals[exp.category] || 0) + exp.amount;
  });

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title || !amount) return;
    const numAmount = Number(amount);

    try {
      await addTripExpense({
        title,
        amount: numAmount,
        category,
        paidBy: 'Me',
        isSplit,
      });
    } catch (err) {
      console.warn('Expense persistence error:', err);
    }

    addAppExpense({
      title,
      amount: numAmount,
      category,
      date: 'Today',
      paidBy: 'Me',
      isSplit,
      splitWith: isSplit ? ['Aman', 'Priya'] : undefined
    });

    setTitle('');
    setAmount('');
    setShowAddModal(false);
  };

  const getCatIcon = (cat: string) => {
    switch (cat) {
      case 'Transport': return <Car className="w-4 h-4 text-[#355F58]" />;
      case 'Hotel': return <Building2 className="w-4 h-4 text-[#355F58]" />;
      case 'Food': return <UtensilsCrossed className="w-4 h-4 text-[#355F58]" />;
      case 'Shopping': return <ShoppingBag className="w-4 h-4 text-[#355F58]" />;
      case 'Activities': return <Compass className="w-4 h-4 text-[#355F58]" />;
      default: return <CreditCard className="w-4 h-4 text-[#355F58]" />;
    }
  };

  return (
    <div className="space-y-6 pb-28 max-w-xl mx-auto animate-fadeIn">
      {/* Header Bar */}
      <div className="flex items-center justify-between pt-1">
        <button
          type="button"
          onClick={() => {
            setTripView('home');
            setActiveTab('trips');
            navigate('/');
          }}
          className="px-3 py-1.5 rounded-xl bg-white hover:bg-[#E8F0EE] text-[#355F58] text-xs font-black flex items-center gap-1.5 border border-[#D9DEDA] transition-all press-scale"
        >
          <ArrowLeft className="w-4 h-4 text-[#355F58]" />
          <span>Back to Trip</span>
        </button>

        <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#E8F0EE] text-[#355F58] border border-[#D9DEDA] text-xs font-bold">
          <Wallet className="w-3.5 h-3.5 text-[#355F58]" />
          <span>{activeDestName} Expenses</span>
        </div>
      </div>

      {/* Hero Financial Overview */}
      <div className="relative rounded-3xl p-6 bg-white border border-[#D9DEDA] shadow-xs space-y-4 overflow-hidden">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#5F6863]">Total Spent</span>
            <div className="text-3xl font-extrabold font-mono text-[#1F2522] mt-0.5">₹{totalSpent.toLocaleString()}</div>
          </div>

          <div className="text-right">
            <span className="text-[10px] font-bold uppercase tracking-wider text-[#5F6863]">Remaining Budget</span>
            <div className={`text-xl font-extrabold font-mono mt-0.5 ${budgetRemaining < 5000 ? 'text-amber-700' : 'text-[#355F58]'}`}>
              ₹{budgetRemaining.toLocaleString()}
            </div>
          </div>
        </div>

        {/* Budget Progress Meter */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-xs font-bold">
            <span className="text-[#5F6863]">Budget Spent ({progressPct}%)</span>
            <span className="text-[#355F58] font-mono">{targetBudget > 0 ? `Target: ₹${targetBudget.toLocaleString()}` : 'No budget set'}</span>
          </div>
          <div className="w-full bg-[#F0F2EF] h-2.5 rounded-full overflow-hidden p-0.5 border border-[#D9DEDA]">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                progressPct > 90 ? 'bg-rose-600' : progressPct > 75 ? 'bg-amber-600' : 'bg-[#355F58]'
              }`}
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* Action Button: Log New Expense */}
        <div className="pt-1 flex gap-2">
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="flex-1 py-3.5 rounded-2xl bg-[#355F58] hover:bg-[#2C504A] text-white font-extrabold text-sm shadow-xs transition-all flex items-center justify-center gap-2 press-scale min-h-[50px]"
          >
            <Plus className="w-5 h-5 text-white" />
            <span>Add Expense</span>
          </button>

          <button
            type="button"
            onClick={() => openAiAssistant(`Analyze my current ${activeDestName} trip expenses of ₹${totalSpent} and suggest money-saving tips.`)}
            className="px-4 py-3.5 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] hover:border-[#355F58]/40 text-[#355F58] font-bold text-xs flex items-center gap-1.5 transition-all min-h-[50px]"
          >
            <Sparkles className="w-4 h-4 text-[#355F58]" />
            <span>AI Budget Advice</span>
          </button>
        </div>
      </div>

      {/* Category Breakdown */}
      <div className="space-y-3">
        <h2 className="text-xs font-bold uppercase tracking-wider text-[#5F6863] flex items-center gap-1.5">
          <PieChart className="w-4 h-4 text-[#355F58]" />
          Category Expense Breakdown
        </h2>

        <div className="grid grid-cols-2 gap-2.5">
          {Object.entries(categoryTotals).map(([cat, val]) => (
            <div key={cat} className="p-3.5 rounded-2xl bg-white border border-[#D9DEDA] space-y-1 shadow-xs">
              <div className="flex items-center justify-between text-xs">
                <span className="font-bold text-[#1F2522] flex items-center gap-1.5">
                  {getCatIcon(cat)}
                  <span>{cat}</span>
                </span>
                <span className="font-extrabold font-mono text-[#355F58]">₹{val.toLocaleString()}</span>
              </div>
              <div className="w-full bg-[#F0F2EF] h-1.5 rounded-full overflow-hidden">
                <div
                  className="bg-[#355F58] h-full rounded-full"
                  style={{ width: `${totalSpent > 0 ? Math.min(100, Math.round((val / totalSpent) * 100)) : 0}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Detailed Expense History List */}
      <div className="space-y-3 pt-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-black uppercase tracking-wider text-[#1F2522]">
            Trip Expense History ({combinedExpenses.length})
          </h2>
          <span className="text-xs text-[#5F6863] font-mono">Sorted by Latest</span>
        </div>

        <div className="space-y-2">
          {combinedExpenses.map((exp) => (
            <div
              key={exp.id}
              className="p-3.5 rounded-2xl bg-white border border-[#D9DEDA] hover:border-[#355F58]/30 transition-all flex items-center justify-between gap-3 shadow-xs"
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-10 h-10 rounded-2xl bg-[#F0F2EF] flex items-center justify-center shrink-0 border border-[#D9DEDA]">
                  {getCatIcon(exp.category)}
                </div>

                <div className="min-w-0">
                  <h4 className="font-extrabold text-sm text-[#1F2522] truncate">{exp.title}</h4>
                  <div className="text-xs text-[#5F6863] flex items-center gap-1.5 mt-0.5">
                    <span>{exp.paidBy}</span>
                    <span>·</span>
                    <span>{exp.date}</span>
                    {exp.isSplit && (
                      <span className="px-1.5 py-0.5 rounded bg-[#E8F0EE] text-[#355F58] text-[10px] font-bold border border-[#D9DEDA]">
                        Split
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <span className="text-base font-black font-mono text-[#355F58] shrink-0">
                ₹{exp.amount.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Log Expense Modal Overlay */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-[#1F2522]/40 backdrop-blur-xs p-4 animate-fadeIn">
          <form
            onSubmit={handleCreate}
            className="w-full max-w-md bg-white border border-[#D9DEDA] rounded-3xl p-6 space-y-4 shadow-xl animate-slideUp text-[#1F2522]"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-black text-[#1F2522]">Log Trip Expense</h3>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                className="text-[#5F6863] hover:text-[#1F2522]"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-bold text-[#5F6863]">Title / Purpose</label>
              <input
                type="text"
                value={title}
                onChange={e => setTitle(e.target.value)}
                placeholder="e.g. Dinner at Beach Shacks"
                className="w-full bg-[#F0F2EF] border border-[#D9DEDA] focus:border-[#355F58] rounded-2xl px-3.5 py-3 text-xs text-[#1F2522] outline-none"
                required
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs font-bold text-[#5F6863]">Amount (₹)</label>
              <input
                type="number"
                value={amount}
                onChange={e => setAmount(e.target.value)}
                placeholder="e.g. 1450"
                className="w-full bg-[#F0F2EF] border border-[#D9DEDA] focus:border-[#355F58] rounded-2xl px-3.5 py-3 text-xs text-[#1F2522] font-mono outline-none"
                required
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs font-bold text-[#5F6863]">Category</label>
              <select
                value={category}
                onChange={e => setCategory(e.target.value as Expense['category'])}
                className="w-full bg-[#F0F2EF] border border-[#D9DEDA] focus:border-[#355F58] rounded-2xl px-3.5 py-3 text-xs text-[#1F2522] outline-none cursor-pointer"
              >
                <option value="Food">Food & Dining</option>
                <option value="Transport">Transport & Rides</option>
                <option value="Hotel">Hotels & Stays</option>
                <option value="Activities">Sightseeing & Activities</option>
                <option value="Shopping">Shopping</option>
                <option value="Other">Other</option>
              </select>
            </div>

            <label className="flex items-center gap-2 text-xs text-[#5F6863] cursor-pointer pt-1">
              <input
                type="checkbox"
                checked={isSplit}
                onChange={e => setIsSplit(e.target.checked)}
                className="w-4 h-4 rounded text-[#355F58] bg-[#F0F2EF] border-[#D9DEDA]"
              />
              <span>Split cost evenly among trip members</span>
            </label>

            <div className="flex gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                className="flex-1 py-3 rounded-2xl bg-[#F0F2EF] text-[#1F2522] border border-[#D9DEDA] font-bold text-xs"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="flex-1 py-3 rounded-2xl bg-[#355F58] hover:bg-[#2C504A] text-white font-black text-xs shadow-xs"
              >
                Save Expense
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};
