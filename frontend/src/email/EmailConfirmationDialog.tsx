import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';

interface EmailConfirmationDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  tone?: 'primary' | 'danger';
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function EmailConfirmationDialog({
  open,
  title,
  description,
  confirmLabel,
  tone = 'danger',
  busy = false,
  onConfirm,
  onCancel,
}: EmailConfirmationDialogProps) {
  const { t } = useTranslation('emailNotifications');
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
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
        ),
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
    <div
      className="email-dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel();
      }}
    >
      <section
        ref={dialogRef}
        className="email-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="email-confirm-title"
        aria-describedby="email-confirm-description"
      >
        <h2 id="email-confirm-title">{title}</h2>
        <p id="email-confirm-description">{description}</p>
        <div className="email-dialog-actions">
          <button
            ref={cancelRef}
            className="btn"
            type="button"
            onClick={onCancel}
            disabled={busy}
          >
            {t('actions.cancel')}
          </button>
          <button
            className={`btn ${tone === 'danger' ? 'btn-danger' : 'btn-primary'}`}
            type="button"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? t('actions.saving') : confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
