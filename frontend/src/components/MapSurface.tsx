import { useEffect, useRef, type ReactNode, type RefObject } from 'react';

/** Uses the same native dialog pattern as AdminDialog, scoped to Map surfaces. */
export default function MapSurface({ narrow, open, onClose, label, className, children, returnFocusRef }: {
  narrow: boolean;
  open: boolean;
  onClose: () => void;
  label: string;
  className: string;
  children: ReactNode;
  returnFocusRef?: RefObject<HTMLElement | null>;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = returnFocusRef?.current ?? document.activeElement as HTMLElement | null;
    const restoreFocus = () => {
      // MapLibre may replace marker elements during a data refresh or resize.
      const markerKey = previous?.dataset.mapMarkerKey;
      const target = markerKey
        ? document.querySelector<HTMLElement>(`[data-map-marker-key="${markerKey}"]`)
        : previous;
      target?.focus({ preventScroll: true });
    };
    if (!narrow) {
      panelRef.current?.querySelector<HTMLButtonElement>('button')?.focus({ preventScroll: true });
      return () => { requestAnimationFrame(restoreFocus); };
    }
    const dialog = dialogRef.current;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog?.showModal();
    return () => {
      dialog?.close();
      document.body.style.overflow = previousOverflow;
      requestAnimationFrame(restoreFocus);
    };
  }, [narrow, open, returnFocusRef]);

  if (!narrow) return <div ref={panelRef} className={className} onKeyDown={event => {
    if (open && event.key === 'Escape') onClose();
  }}>{children}</div>;

  return <dialog ref={dialogRef} className={className} aria-label={label}
    onKeyDown={event => {
      // The existing date-range popover handles its own Escape before this sheet.
      if (event.key === 'Escape' && (event.target as HTMLElement).closest('[role="dialog"]')) event.preventDefault();
    }}
    onCancel={event => { event.preventDefault(); onClose(); }}
    onClick={event => {
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.target === event.currentTarget && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) onClose();
    }}>
    {children}
  </dialog>;
}
