import i18n from './i18n';

function isKnownRole(code: string): code is 'admin' | 'analyst' | 'viewer' {
  return code === 'admin' || code === 'analyst' || code === 'viewer';
}

export function roleLabel(code: string): string {
  return isKnownRole(code) ? i18n.t(`users:roles.${code}.name`) : code;
}

export function roleDescription(code: string, description?: string | null): string {
  return isKnownRole(code) ? i18n.t(`users:roles.${code}.description`) : description || '';
}
