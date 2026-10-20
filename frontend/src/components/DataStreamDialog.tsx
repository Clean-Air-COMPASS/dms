import { useEffect, useRef, type ReactNode } from 'react';
import i18n from '../i18n';
import './DataStreamDialog.css';

/** Shared native modal for the measurement and AQI selector branches. */
export default function DataStreamDialog({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current;
    dialog?.showModal();
    return () => {
      dialog?.close();
      previous?.focus();
    };
  }, []);

  return (
    <dialog
      ref={ref}
      className="data-stream-dialog"
      aria-label={i18n.t('analytics:dataStreamSelectionModal.accessibility.selectDataStream')}
      onKeyDown={(event) => {
        if (event.key !== 'Tab') return;
        // Both selector branches begin with Close and end with Cancel.
        // Wrap these boundaries instead of allowing native Tab to enter browser chrome.
        const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');
        const first = buttons[0];
        const last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => {
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.target === event.currentTarget && (
          event.clientX < bounds.left || event.clientX > bounds.right
          || event.clientY < bounds.top || event.clientY > bounds.bottom
        )) onClose();
      }}
    >
      {children}
    </dialog>
  );
}
