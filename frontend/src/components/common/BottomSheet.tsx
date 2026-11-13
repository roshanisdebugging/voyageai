import React, { useEffect, useCallback, useRef, useState, useId } from 'react';
import { X } from 'lucide-react';

interface BottomSheetProps {
  isOpen: boolean;
  onClose: () => void;
  children: React.ReactNode;
  height?: 'peek' | 'half' | 'expanded' | 'full';
  showHandle?: boolean;
  className?: string;
  title?: string;
}

const heightMap = {
  peek: '38dvh',
  half: '58dvh',
  expanded: '85dvh',
  full: '96dvh',
};

export const BottomSheet: React.FC<BottomSheetProps> = ({
  isOpen,
  onClose,
  children,
  height = 'half',
  showHandle = true,
  className = '',
  title,
}) => {
  const titleId = useId();
  const sheetRef = useRef<HTMLDivElement>(null);
  const [dragY, setDragY] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const startYRef = useRef(0);
  const currentYRef = useRef(0);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    },
    [onClose]
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
      setDragY(0);
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [isOpen, handleKeyDown]);

  // Touch Drag Listeners
  const handleTouchStart = (e: React.TouchEvent) => {
    const touch = e.touches[0];
    startYRef.current = touch.clientY;
    currentYRef.current = touch.clientY;
    setIsDragging(true);
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    if (!isDragging) return;
    const touch = e.touches[0];
    const deltaY = touch.clientY - startYRef.current;
    if (deltaY > 0) {
      setDragY(deltaY);
    }
    currentYRef.current = touch.clientY;
  };

  const handleTouchEnd = () => {
    if (!isDragging) return;
    setIsDragging(false);
    const deltaY = currentYRef.current - startYRef.current;
    // Dismiss threshold: drag down > 110px
    if (deltaY > 110) {
      onClose();
    } else {
      setDragY(0);
    }
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className={`sheet-backdrop ${isOpen ? 'open' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Sheet Modal */}
      <div
        ref={sheetRef}
        className={`sheet-container ${isOpen ? 'open' : ''} ${className}`}
        style={{
          maxHeight: heightMap[height],
          transform: isOpen ? `translateY(${dragY}px)` : 'translateY(100%)',
          transition: isDragging ? 'none' : 'transform 0.3s cubic-bezier(0.32, 0.72, 0, 1)',
        }}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
      >
        {/* Handle bar with Touch Listener */}
        {showHandle && (
          <div
            className="sheet-handle-zone"
            onTouchStart={handleTouchStart}
            onTouchMove={handleTouchMove}
            onTouchEnd={handleTouchEnd}
          >
            <div className="sheet-handle" />
          </div>
        )}

        {/* Optional Title Header */}
        {title && (
          <div className="px-5 py-3 border-b border-[var(--color-border)] flex items-center justify-between gap-3 shrink-0">
            <h3 id={titleId} className="min-w-0 wrap-anywhere text-base font-extrabold text-[var(--color-text-primary)]">{title}</h3>
            <button
              type="button"
              onClick={onClose}
              className="w-11 h-11 rounded-full hover:bg-[var(--color-surface-elevated)] flex items-center justify-center text-[var(--color-text-primary)] focus-visible:outline-2 focus-visible:outline-[var(--color-primary)] transition-colors press-scale shrink-0"
              aria-label="Close sheet"
              title="Close"
            >
              <X className="w-4 h-4" aria-hidden="true" />
            </button>
          </div>
        )}

        {/* Scrollable Content Body */}
        <div className="flex-1 overflow-y-auto overscroll-contain">
          {children}
        </div>
      </div>
    </>
  );
};
