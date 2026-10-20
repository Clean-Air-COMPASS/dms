import { Trans } from 'react-i18next';


interface StartupStatusProps {
  persistentFailure: boolean;
  onRetry: () => void;
}


export default function StartupStatus({
  persistentFailure,
  onRetry,
}: StartupStatusProps) {
  return (
    <main className="startup-status-page">
      <section
        className="startup-status-card"
        role="status"
        aria-live="polite"
        aria-busy={!persistentFailure}
      >
        <div className="startup-status-brand" aria-hidden="true">
          <div className="startup-status-mark">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2L15 8H9L12 2Z" fill="currentColor" opacity="0.9" />
              <circle cx="12" cy="16" r="5" stroke="currentColor" strokeWidth="1.5" opacity="0.6" />
            </svg>
          </div>
          <span><Trans ns="setup" i18nKey="setupWizard.headings.productName" /></span>
        </div>

        {!persistentFailure ? (
          <>
            <div className="startup-status-spinner" aria-hidden="true" />
            <h1><Trans ns="setup" i18nKey="startup.headings.starting" /></h1>
            <p><Trans ns="setup" i18nKey="startup.text.starting" /></p>
          </>
        ) : (
          <>
            <div className="startup-status-paused" aria-hidden="true">!</div>
            <h1><Trans ns="setup" i18nKey="startup.headings.failure" /></h1>
            <p><Trans ns="setup" i18nKey="startup.text.failure" /></p>
            <button type="button" className="setup-btn setup-btn-primary" onClick={onRetry}>
              <Trans ns="setup" i18nKey="startup.actions.retry" />
            </button>
          </>
        )}
      </section>
    </main>
  );
}
