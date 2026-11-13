import React from 'react';
import { useApp } from '../../context/AppContext';
import { BottomSheet } from './BottomSheet';
import { CheckCircle2, Car, CloudSun, Calendar, Sparkles } from 'lucide-react';

export const NotificationDrawer: React.FC = () => {
  const { notifications, isNotificationsOpen, setIsNotificationsOpen, markNotificationAsRead } = useApp();

  const getIcon = (type: string) => {
    switch (type) {
      case 'cab': return <Car className="w-4 h-4 text-teal-400" />;
      case 'weather': return <CloudSun className="w-4 h-4 text-amber-400" />;
      case 'reminder': return <Calendar className="w-4 h-4 text-slate-300" />;
      case 'booking': return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
      default: return <Sparkles className="w-4 h-4 text-slate-300" />;
    }
  };

  return (
    <BottomSheet isOpen={isNotificationsOpen} onClose={() => setIsNotificationsOpen(false)} height="half">
      <div className="px-5 py-3 border-b border-white/[0.06] shrink-0">
        <h2 className="text-[15px] font-semibold text-white">Notifications</h2>
      </div>
      <div className="px-5 py-3 space-y-1 overflow-y-auto">
        {notifications.length === 0 ? (
          <p className="py-8 text-center text-meta">No notifications</p>
        ) : (
          notifications.map(n => (
            <button
              key={n.id}
              onClick={() => markNotificationAsRead(n.id)}
              className={`w-full text-left press-scale flex gap-3 py-3 border-b border-white/[0.04] last:border-0 ${n.read ? 'opacity-50' : ''}`}
            >
              <div className="w-9 h-9 rounded-xl bg-white/[0.04] flex items-center justify-center shrink-0 mt-0.5">
                {getIcon(n.type)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-medium text-white truncate">{n.title}</h4>
                  <span className="text-micro text-[11px] shrink-0 ml-2">{n.time}</span>
                </div>
                <p className="text-meta text-[13px] mt-0.5 line-clamp-2">{n.message}</p>
              </div>
            </button>
          ))
        )}
      </div>
    </BottomSheet>
  );
};
