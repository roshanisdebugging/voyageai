import React, { useState } from 'react';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { X, Car } from 'lucide-react';
import { mockCabOptions } from '../../data/mockData';
import confetti from 'canvas-confetti';

export const CabBookingModal: React.FC = () => {
  const { isCabModalOpen, setIsCabModalOpen, cabDestination, addBooking } = useApp();
  const { addTransport, addExpense: addTripExpense } = useTrip();
  const [selectedCabId, setSelectedCabId] = useState<string>('cab-sedan');
  const [pickupLoc, setPickupLoc] = useState<string>('Current Location');
  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  const [isConfirmed, setIsConfirmed] = useState<boolean>(false);

  if (!isCabModalOpen) return null;

  const cab = mockCabOptions.find(c => c.id === selectedCabId) || mockCabOptions[0];

  const handleBookCab = async () => {
    setIsProcessing(true);
    try {
      await addTransport({
        transportType: 'CAB',
        providerName: cab.name,
        pickupLocation: pickupLoc,
        dropoffLocation: cabDestination,
        pickupTime: 'Immediate',
        estimatedFare: cab.estimatedFare,
        status: 'SELECTED',
      });

      await addTripExpense({
        title: `Cab Ride to ${cabDestination}`,
        amount: cab.estimatedFare,
        category: 'Transport',
        paidBy: 'Me',
        isSplit: true,
      });
    } catch (err) {
      console.warn('Transport persistence error:', err);
    }

    setIsProcessing(false);
    setIsConfirmed(true);
    confetti({ particleCount: 60, spread: 50, origin: { y: 0.7 } });

    addBooking({
      id: `bk-cab-${Date.now()}`,
      type: 'cab',
      title: `Cab Ride to ${cabDestination}`,
      status: 'in-transit',
      dateTime: 'Now (Dispatching)',
      location: `Pickup: ${pickupLoc}`,
      confirmationCode: `CAB-GOA-${Math.floor(100 + Math.random() * 900)}`,
      amount: cab.estimatedFare,
      paymentStatus: 'paid',
      details: {
        'Vehicle': cab.name,
        'ETA': `${cab.etaMinutes} mins`,
        'Driver': 'Rajesh Kumar (+91 98765 43210)'
      },
      image: cab.image
    });
  };

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4 bg-[#1F2522]/60 backdrop-blur-sm animate-fadeIn overflow-y-auto">
      <div className="w-full max-w-lg bg-white border border-[#D9DEDA] rounded-3xl p-6 space-y-5 shadow-2xl relative text-[#1F2522] my-auto">
        
        <button 
          onClick={() => { setIsCabModalOpen(false); setIsConfirmed(false); }}
          className="absolute top-4 right-4 p-2 rounded-xl bg-[#F0F2EF] text-[#5F6863] hover:text-[#1F2522] press-scale"
        >
          <X className="w-5 h-5" />
        </button>

        {!isConfirmed ? (
          <>
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-2xl bg-[#E8F0EE] text-[#355F58] border border-[#D9DEDA]">
                <Car className="w-6 h-6 text-[#355F58]" />
              </div>
              <div>
                <h3 className="font-extrabold text-xl text-[#1F2522]">Book Local Ride</h3>
                <p className="text-xs text-[#5F6863] font-medium">Estimated fare based on current location</p>
              </div>
            </div>

            {/* Route Inputs */}
            <div className="space-y-3 p-4 rounded-2xl bg-[#F0F2EF] border border-[#D9DEDA] text-xs">
              <div>
                <label className="text-[#5F6863] font-bold">Pickup Location</label>
                <input 
                  type="text" 
                  value={pickupLoc}
                  onChange={(e) => setPickupLoc(e.target.value)}
                  className="w-full bg-white border border-[#D9DEDA] rounded-xl px-3.5 py-2.5 text-[#1F2522] mt-1 font-medium text-sm focus:outline-none focus:border-[#355F58]"
                />
              </div>
              <div>
                <label className="text-[#5F6863] font-bold">Destination</label>
                <input 
                  type="text" 
                  readOnly
                  value={cabDestination || 'Selected Destination'}
                  className="w-full bg-[#E8F0EE] border border-[#D9DEDA] rounded-xl px-3.5 py-2.5 text-[#355F58] mt-1 font-bold text-sm cursor-not-allowed"
                />
              </div>
            </div>

            {/* Vehicle Selector */}
            <div className="space-y-2">
              <label className="text-xs font-bold text-[#5F6863] uppercase tracking-wider">Choose Ride Type</label>
              <div className="space-y-2.5 max-h-56 overflow-y-auto pr-1">
                {mockCabOptions.map(c => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setSelectedCabId(c.id)}
                    className={`w-full p-3 rounded-2xl border text-left flex items-center justify-between transition-all press-scale ${
                      selectedCabId === c.id
                        ? 'bg-[#E8F0EE] border-[#355F58] text-[#1F2522] shadow-xs ring-1 ring-[#355F58]'
                        : 'bg-[#F0F2EF] border-[#D9DEDA] text-[#5F6863] hover:border-[#355F58]/40'
                    }`}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <img 
                        src={c.image} 
                        alt={c.name} 
                        className="w-14 h-11 object-cover rounded-xl border border-[#D9DEDA] shrink-0 bg-white" 
                        loading="lazy"
                        decoding="async"
                      />
                      <div className="min-w-0">
                        <div className="font-extrabold text-sm text-[#1F2522] truncate">{c.name}</div>
                        <div className="text-xs text-[#5F6863] font-medium truncate">{c.capacity} · ~{c.etaMinutes} mins away</div>
                      </div>
                    </div>
                    <div className="text-right shrink-0 ml-2">
                      <div className="font-extrabold text-sm text-[#355F58]">₹{c.estimatedFare}</div>
                      <div className="text-[10px] text-[#5F6863] font-semibold">Estimated</div>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <button
              type="button"
              onClick={handleBookCab}
              disabled={isProcessing}
              className="w-full py-4 rounded-2xl bg-[#355F58] hover:bg-[#2C504A] text-white font-extrabold text-base flex items-center justify-center gap-2 shadow-xs press-scale min-h-[54px] disabled:opacity-50"
            >
              {isProcessing ? 'Dispatching Ride...' : `Confirm & Book Ride (₹${cab.estimatedFare})`}
            </button>
          </>
        ) : (
          <div className="py-6 text-center space-y-4">
            <div className="w-14 h-14 rounded-full bg-[#E8F0EE] text-[#355F58] border border-[#D9DEDA] flex items-center justify-center mx-auto animate-bounce">
              <Car className="w-7 h-7 text-[#355F58]" />
            </div>
            <h3 className="text-xl font-extrabold text-[#1F2522]">Ride Dispatched!</h3>
            <p className="text-xs text-[#5F6863]">
              Driver <span className="font-bold text-[#355F58]">Rajesh Kumar</span> (GA-03-Z-8821) is 4 mins away.
            </p>
            <button
              onClick={() => { setIsCabModalOpen(false); setIsConfirmed(false); }}
              className="w-full py-3.5 rounded-2xl bg-[#F0F2EF] text-[#1F2522] font-bold text-sm border border-[#D9DEDA]"
            >
              Done
            </button>
          </div>
        )}

      </div>
    </div>
  );
};
