import React, { useState } from 'react';
import { useApp } from '../../context/AppContext';
import { useTrip } from '../../features/trip/TripContext';
import { X, Star, MapPin, Check, ShieldCheck } from 'lucide-react';
import confetti from 'canvas-confetti';

export const HotelDetailModal: React.FC = () => {
  const { selectedHotel, setSelectedHotel, addBooking } = useApp();
  const { addStay, addExpense: addTripExpense } = useTrip();
  const [selectedRoomId, setSelectedRoomId] = useState<string>('r1');
  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  const [bookingSuccess, setBookingSuccess] = useState<boolean>(false);

  if (!selectedHotel) return null;

  const room = selectedHotel.rooms.find(r => r.id === selectedRoomId) || selectedHotel.rooms[0];
  const totalWithTax = room.price * 4 + 1800; // 4 nights + taxes

  const handleBookHotel = async () => {
    setIsProcessing(true);
    try {
      await addStay({
        hotelName: selectedHotel.name,
        locationName: selectedHotel.location,
        checkInDate: '2026-10-15',
        checkOutDate: '2026-10-19',
        nights: 4,
        pricePerNight: room.price,
        totalPrice: totalWithTax,
        status: 'SELECTED',
      });

      await addTripExpense({
        title: `${selectedHotel.name} Stay`,
        amount: totalWithTax,
        category: 'Hotel',
        paidBy: 'Me',
        isSplit: true,
      });
    } catch (err) {
      console.warn('Stay persistence error:', err);
    }

    setIsProcessing(false);
    setBookingSuccess(true);
    confetti({ particleCount: 80, spread: 60, origin: { y: 0.6 } });

    addBooking({
      id: `bk-htl-${Date.now()}`,
      type: 'hotel',
      title: `${selectedHotel.name} (${room.type})`,
      status: 'confirmed',
      dateTime: 'Check-in: 12 Sep 2026, 12:00 PM',
      location: selectedHotel.location,
      confirmationCode: `HTL-${Math.floor(100000 + Math.random() * 900000)}`,
      amount: totalWithTax,
      paymentStatus: 'paid',
      details: {
        'Room Type': room.type,
        'Capacity': room.capacity,
        'Inclusions': 'Breakfast, Free Wi-Fi, Beach Access'
      },
      image: selectedHotel.photos[0]
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn overflow-y-auto">
      <div className="w-full max-w-2xl glass-panel bg-[#0B111E] border-white/10 rounded-3xl p-6 space-y-6 max-h-[90vh] overflow-y-auto shadow-2xl relative">
        
        {/* Close button */}
        <button 
          onClick={() => { setSelectedHotel(null); setBookingSuccess(false); }}
          className="absolute top-4 right-4 p-2 rounded-xl bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white"
        >
          <X className="w-5 h-5" />
        </button>

        {!bookingSuccess ? (
          <>
            {/* Header */}
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-bold uppercase px-2.5 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                  {selectedHotel.propertyType}
                </span>
                <span className="text-xs text-amber-400 font-bold flex items-center gap-1">
                  <Star className="w-3.5 h-3.5 fill-amber-400" /> {selectedHotel.rating} ({selectedHotel.reviewsCount} reviews)
                </span>
              </div>
              <h2 className="text-2xl font-extrabold text-white mt-1">{selectedHotel.name}</h2>
              <p className="text-xs text-slate-400 flex items-center gap-1 mt-0.5">
                <MapPin className="w-3.5 h-3.5 text-teal-400" /> {selectedHotel.location}
              </p>
            </div>

            {/* Gallery Grid */}
            <div className="grid grid-cols-3 gap-2 h-44 rounded-2xl overflow-hidden">
              {selectedHotel.photos.map((p, idx) => (
                <img key={idx} src={p} alt={`${selectedHotel.name} photo ${idx + 1}`} className="w-full h-full object-cover bg-slate-800" loading="lazy" decoding="async" />
              ))}
            </div>

            {/* Amenities */}
            <div>
              <h3 className="font-bold text-xs text-slate-300 uppercase tracking-wider mb-2">Amenities</h3>
              <div className="flex flex-wrap gap-2">
                {selectedHotel.amenities.map((a, i) => (
                  <span key={i} className="text-xs px-3 py-1 rounded-lg bg-white/5 text-slate-300 border border-white/10 flex items-center gap-1.5">
                    <Check className="w-3 h-3 text-teal-400" /> {a}
                  </span>
                ))}
              </div>
            </div>

            {/* Room Selection */}
            <div>
              <h3 className="font-bold text-xs text-slate-300 uppercase tracking-wider mb-2">Select Room</h3>
              <div className="space-y-2">
                {selectedHotel.rooms.map((r) => (
                  <div
                    key={r.id}
                    onClick={() => setSelectedRoomId(r.id)}
                    className={`p-3.5 rounded-xl border transition-all cursor-pointer flex items-center justify-between ${
                      selectedRoomId === r.id
                        ? 'bg-teal-500/15 border-teal-500/50 shadow-md shadow-teal-500/5'
                        : 'bg-white/5 border-white/10 hover:bg-white/10'
                    }`}
                  >
                    <div>
                      <h4 className="font-bold text-sm text-white">{r.type}</h4>
                      <p className="text-xs text-slate-400">{r.bed} • {r.capacity}</p>
                    </div>
                    <span className="font-mono font-bold text-teal-400 text-sm">₹{r.price.toLocaleString()} / night</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Price Breakdown & CTA */}
            <div className="p-4 rounded-2xl bg-white/5 border border-white/10 space-y-3">
              <div className="flex items-center justify-between text-xs text-slate-300">
                <span>Room Subtotal (4 Nights):</span>
                <span className="font-mono">₹{(room.price * 4).toLocaleString()}</span>
              </div>
              <div className="flex items-center justify-between text-xs text-slate-300">
                <span>Taxes & Luxury Resort Service Fee:</span>
                <span className="font-mono">₹1,800</span>
              </div>
              <div className="flex items-center justify-between pt-2 border-t border-white/10 text-sm font-bold text-white">
                <span>Total Amount:</span>
                <span className="font-mono text-teal-400">₹{totalWithTax.toLocaleString()}</span>
              </div>

              <button
                onClick={handleBookHotel}
                disabled={isProcessing}
                className="w-full py-3 rounded-xl bg-gradient-to-r from-teal-500 to-indigo-600 hover:from-teal-400 hover:to-indigo-500 text-white font-bold text-sm shadow-xl shadow-teal-500/20 flex items-center justify-center gap-2 transition-all disabled:opacity-50"
              >
                {isProcessing ? 'Confirming Hotel Booking...' : 'Book Hotel Now'}
              </button>
            </div>
          </>
        ) : (
          <div className="py-8 text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 flex items-center justify-center mx-auto">
              <ShieldCheck className="w-8 h-8" />
            </div>
            <h3 className="text-2xl font-extrabold text-white">Hotel Booking Confirmed!</h3>
            <p className="text-xs text-slate-300 max-w-md mx-auto">
              Your stay at <span className="font-bold text-teal-300">{selectedHotel.name}</span> has been added to your unified trip bookings and expense ledger.
            </p>
            <button
              onClick={() => { setSelectedHotel(null); setBookingSuccess(false); }}
              className="px-8 py-3 rounded-xl bg-teal-500 text-slate-950 font-bold text-sm"
            >
              Done
            </button>
          </div>
        )}

      </div>
    </div>
  );
};
