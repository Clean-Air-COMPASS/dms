import { useEffect, useRef, type ReactNode, type RefObject } from 'react';

/** Native modal supplies focus containment, Escape, and background inertness. */
export default function UsersDialog({ title, onClose, children, returnFocusRef }: { title: string; onClose: () => void; children: ReactNode; returnFocusRef?: RefObject<HTMLElement | null> }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = returnFocusRef?.current || document.activeElement as HTMLElement | null;
    const dialog = ref.current;
    dialog?.showModal();
    return () => { dialog?.close(); queueMicrotask(() => previous?.focus()); };
  }, [returnFocusRef]);
  return <dialog ref={ref} className="users-dialog" aria-labelledby="users-dialog-title"
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onKeyDown={(event) => {
      if (event.key !== 'Tab') return;
      const controls = event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), a[href], select:not(:disabled)');
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first?.focus();
      }
    }}>
    <h2 id="users-dialog-title">{title}</h2>
    {children}
  </dialog>;
}
