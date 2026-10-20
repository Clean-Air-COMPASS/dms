import { Trans } from 'react-i18next';
import i18n from './i18n';
export default function LoadingSplash({ message }: { message?: string }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#f8fafc]">
      <div className="flex flex-col items-center gap-6">
        <div className="flex items-center gap-3">
          <div className="w-14 h-14 rounded-full bg-white shadow-lg flex items-center justify-center">
            <svg className="w-8 h-8 text-blue-600" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2L15 8H9L12 2Z" fill="currentColor" opacity="0.9"/>
              <circle cx="12" cy="16" r="5" stroke="currentColor" strokeWidth="1.5" opacity="0.6"/>
            </svg>
          </div>
          <div className="text-2xl font-semibold tracking-wide text-slate-800">COMPASS</div>
        </div>

        <div className="flex items-center gap-3">
          <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-blue-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path>
          </svg>
          <div className="text-sm text-slate-600">{message || i18n.t('admin:loadingSplash.text.initializing')}</div>
        </div>

        <div className="text-xs text-slate-400"><Trans ns="admin" i18nKey="loadingSplash.text.loadingRequiredServicesMayTakeFew" /></div>
      </div>
    </div>
  );
}
