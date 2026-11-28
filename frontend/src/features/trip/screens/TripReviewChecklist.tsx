import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Pencil, type LucideIcon } from 'lucide-react';

export interface TripReviewItem {
  id: string;
  label: string;
  icon: LucideIcon;
  value: string;
  detail?: string;
  editor: ReactNode;
}

export function TripReviewChecklist({ items }: { items: TripReviewItem[] }) {
  const [openItem, setOpenItem] = useState<string | null>(null);
  const editorHeading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (openItem) editorHeading.current?.focus();
  }, [openItem]);

  return (
    <ul className="divide-y divide-(--itinerary-border) border-y border-(--itinerary-border)">
      {items.map(({ id, label, icon: Icon, value, detail, editor }) => {
        const open = openItem === id;
        const editorId = `review-editor-${id}`;

        return (
          <li key={id}>
            <div className="grid min-h-[70px] grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 py-2.5 sm:gap-3">
              <Icon size={19} aria-hidden="true" className="text-(--itinerary-accent)" />
              <div className="flex min-w-0 flex-col gap-0.5 [overflow-wrap:anywhere]">
                <span className="text-xs font-semibold text-(--itinerary-muted)">{label}</span>
                <strong className="text-sm font-bold">{value}</strong>
                {detail && <span className="text-xs text-(--itinerary-muted)">{detail}</span>}
              </div>
              <button
                type="button"
                aria-label={`Edit ${label.toLowerCase()}`}
                aria-expanded={open}
                aria-controls={editorId}
                className="trip-review-edit"
                onClick={event => {
                  opener.current = event.currentTarget;
                  setOpenItem(open ? null : id);
                }}
              >
                <Pencil size={15} aria-hidden="true" />
                Edit
              </button>
            </div>
            <div id={editorId} hidden={!open}>
              {open && (
                <div className="mb-2.5 grid gap-3 rounded-xl bg-(--color-surface-elevated) p-2.5 sm:p-3">
                  <h3 ref={editorHeading} tabIndex={-1} className="text-[15px] font-bold">Edit {label.toLowerCase()}</h3>
                  {editor}
                  <button
                    type="button"
                    className="trip-review-edit trip-review-done justify-self-end"
                    onClick={() => {
                      setOpenItem(null);
                      opener.current?.focus();
                    }}
                  >
                    Done
                  </button>
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
