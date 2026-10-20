import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';

export default function QcConfirmationDialog({
  open,
  title,
  description,
  confirmLabel,
  busy,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation('qualityControl');
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    cancelRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== 'Tab' || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>('button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previouslyFocused?.focus();
    };
  }, [busy, onCancel, open]);

  if (!open) return null;
  return (
    <div className="qc-dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !busy) onCancel();
    }}>
      <section
        ref={dialogRef}
        className="qc-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="qc-confirm-title"
        aria-describedby="qc-confirm-description"
      >
        <h2 id="qc-confirm-title">{title}</h2>
        <p id="qc-confirm-description">{description}</p>
        <div className="qc-dialog-actions">
          <button ref={cancelRef} className="btn" type="button" onClick={onCancel} disabled={busy}>
            {t('actions.cancel')}
          </button>
          <button className="btn btn-danger" type="button" onClick={onConfirm} disabled={busy}>
            {busy ? t('actions.resetting') : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
