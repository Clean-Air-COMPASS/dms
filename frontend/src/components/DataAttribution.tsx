import { Trans, useTranslation } from 'react-i18next';
import type { DataAttribution as DataAttributionValue } from '../dataAttribution';

// Attribution links are public references, never authenticated API endpoints.
function publicAttributionUrl(value: string | null): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return undefined;
    if (/(?:token|key|secret|password|credential|authorization|signature)/i.test(url.search + url.hash)) return undefined;
    return value;
  } catch {
    return undefined;
  }
}

export default function DataAttribution({ value }: { value: DataAttributionValue | null | undefined }) {
  const { t } = useTranslation('common');
  if (!value) return null;

  const providerName = value.data_provider_name || value.hardware_provider_name;
  const isAirGradientViaOpenAQ = value.hardware_provider_name === 'AirGradient'
    && value.data_provider_name === 'OpenAQ';
  const providerUrl = publicAttributionUrl(value.provider_url);
  const contributorUrl = publicAttributionUrl(value.contributor_url);
  const licenseUrl = publicAttributionUrl(value.license_url);
  if (!providerName && !value.contributor_name && !value.license_code
    && value.acquisition_path !== 'airgradient_authenticated') return null;

  return (
    <aside className="min-w-0 [overflow-wrap:anywhere] rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-700" aria-label={t('dataAttribution.label')}>
      <div>
        {isAirGradientViaOpenAQ ? (
          <Trans ns="common" i18nKey="dataAttribution.airGradientViaOpenAQ"
            components={{
              airGradient: <a className="underline" href="https://www.airgradient.com" target="_blank" rel="noreferrer" />,
              openAQ: <a className="underline" href={providerUrl || 'https://openaq.org'} target="_blank" rel="noreferrer" />,
            }}
          />
        ) : providerName ? (
          <Trans ns="common" i18nKey="dataAttribution.providedBy" values={{ provider: providerName }}
            components={{ providerLink: providerUrl ? <a className="underline" href={providerUrl} target="_blank" rel="noreferrer" /> : <span /> }}
          />
        ) : null}
      </div>
      {value.contributor_name && (
        <div>
          <Trans ns="common" i18nKey="dataAttribution.contributor" values={{ contributor: value.contributor_name }}
            components={{ contributorLink: contributorUrl ? <a className="underline" href={contributorUrl} target="_blank" rel="noreferrer" /> : <span /> }}
          />
        </div>
      )}
      {value.license_code ? (
        <div>
          <Trans ns="common" i18nKey="dataAttribution.license" values={{ license: value.license_code }}
            components={{ licenseLink: licenseUrl ? <a className="underline" href={licenseUrl} target="_blank" rel="noreferrer" /> : <span /> }}
          />
        </div>
      ) : value.acquisition_path === 'airgradient_authenticated' ? (
        <div><Trans ns="common" i18nKey="dataAttribution.authenticatedOwnerControlled" /></div>
      ) : null}
    </aside>
  );
}
