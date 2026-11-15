import { useEffect, useId, useRef, type ReactNode } from 'react';
import { X, type LucideIcon } from 'lucide-react';

interface ItineraryAiDialogProps {
  icon: LucideIcon;
  title: string;
  description: string;
  actionLabel: string;
  onDismiss: () => void;
  children: ReactNode;
}

export function ItineraryAiDialog({
  icon: Icon,
  title,
  description,
  actionLabel,
  onDismiss,
  children,
}: ItineraryAiDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  const dismiss = () => {
    dialogRef.current?.close();
    onDismiss();
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onCancel={event => {
        event.preventDefault();
        dismiss();
      }}
      className="fixed inset-0 m-auto max-h-[calc(100dvh-2*max(0.5rem,env(safe-area-inset-top),env(safe-area-inset-bottom)))] w-[calc(100%-2*max(0.5rem,env(safe-area-inset-left),env(safe-area-inset-right)))] max-w-md overflow-hidden rounded-3xl border border-(--itinerary-border) bg-(--color-surface) p-0 text-left text-(--color-text-primary) shadow-2xl open:flex open:flex-col backdrop:bg-[#1F2522]/50 backdrop:backdrop-blur-xs [&_button:focus-visible]:outline-2 [&_button:focus-visible]:-outline-offset-2 [&_button:focus-visible]:outline-(--itinerary-accent)"
    >
      <header className="flex shrink-0 items-center gap-3 border-b border-(--color-border) px-4 py-3 [@media(max-height:420px)]:py-1.5 dark:border-zinc-700">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-2xl bg-(--itinerary-accent-surface) text-(--itinerary-accent)">
          <Icon className="size-5" aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1 wrap-anywhere">
          <h3 id={titleId} className="text-base font-extrabold">{title}</h3>
          <p id={descriptionId} className="text-xs font-medium text-(--color-text-secondary) [@media(max-height:420px)]:sr-only">
            {description}
          </p>
        </div>
        <button
          type="button"
          onClick={dismiss}
          aria-label="Close"
          className="flex size-11 shrink-0 items-center justify-center rounded-full border border-(--itinerary-control-border) bg-(--color-surface-elevated) text-(--itinerary-muted) hover:text-(--color-text-primary)"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </header>
      <div
        tabIndex={0}
        role="region"
        aria-labelledby={titleId}
        className="min-h-0 space-y-3.5 overflow-y-auto overscroll-contain px-4 py-3.5 wrap-anywhere focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-(--color-primary) [@media(max-height:420px)]:py-2.5"
      >
        {children}
      </div>
      <footer className="shrink-0 border-t border-(--color-border) px-4 py-2.5 [@media(max-height:420px)]:py-1.5">
        <button
          type="button"
          onClick={dismiss}
          className="min-h-11 w-full rounded-2xl bg-(--color-primary) px-3 py-3 text-xs font-extrabold text-white shadow-xs press-scale hover:brightness-[0.93] dark:text-[#092319]"
        >
          {actionLabel}
        </button>
      </footer>
    </dialog>
  );
}
