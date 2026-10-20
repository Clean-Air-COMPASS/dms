import { useEffect, useId, useRef, type ReactNode } from 'react';

/** Provider confirmation: native focus containment, Escape and focus return. */
export default function AdminDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current;
    dialog?.showModal();
    return () => { dialog?.close(); previous?.focus(); };
  }, []);
  return (
    <dialog ref={ref} className="admin-dialog" aria-labelledby={titleId}
      onCancel={event => { event.preventDefault(); onClose(); }}
      onClick={event => {
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.target === event.currentTarget && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) onClose();
      }}>
      <h2 id={titleId}>{title}</h2>
      {children}
    </dialog>
  );
}
