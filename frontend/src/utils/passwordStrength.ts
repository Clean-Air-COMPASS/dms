import i18n from '../i18n';

export interface PasswordCheck {
  
  key: string;
  
  label: string;
  
  passed: boolean;
}

export interface PasswordStrengthResult {
  
  isValid: boolean;
  
  checks: PasswordCheck[];
  
  warning?: string;
}


export function validatePasswordStrength(
  password: string,
  email?: string
): PasswordStrengthResult {
  const checks: PasswordCheck[] = [];

  
  const minLength = 12;
  checks.push({
    key: 'length',
    label: i18n.t('auth:passwordRequirements.minimumLength', { count: minLength }),
    passed: password.length >= minLength,
  });

  
  checks.push({
    key: 'uppercase',
    label: i18n.t('auth:passwordRequirements.uppercase'),
    passed: /[A-Z]/.test(password),
  });

  
  checks.push({
    key: 'lowercase',
    label: i18n.t('auth:passwordRequirements.lowercase'),
    passed: /[a-z]/.test(password),
  });

  
  checks.push({
    key: 'number',
    label: i18n.t('auth:passwordRequirements.number'),
    passed: /[0-9]/.test(password),
  });

  
  checks.push({
    key: 'special',
    label: i18n.t('auth:passwordRequirements.specialCharacter'),
    passed: /[^A-Za-z0-9]/.test(password),
  });
  
  let containsEmail = false;
  if (email && email.length > 0) {
    const emailLower = email.toLowerCase();
    const passwordLower = password.toLowerCase();
    
    const localPart = emailLower.split('@')[0];
    containsEmail =
      passwordLower.includes(emailLower) ||
      (localPart.length >= 3 && passwordLower.includes(localPart));
  }
  checks.push({
    key: 'noEmail',
    label: i18n.t('auth:passwordRequirements.excludesEmail'),
    passed: !containsEmail,
  });

  const isValid = checks.every((c) => c.passed);

  
  let warning: string | undefined;
  if (isValid && password.length < 16) {
    warning = i18n.t('auth:passwordRequirements.longerPasswordSuggestion');
  }

  return { isValid, checks, warning };
}


export function getPasswordStrengthScore(password: string): number {
  if (!password) return 0;

  let score = 0;

  
  score += Math.min(password.length * 3, 40);

  
  if (/[a-z]/.test(password)) score += 10;
  if (/[A-Z]/.test(password)) score += 10;
  if (/[0-9]/.test(password)) score += 10;
  if (/[^A-Za-z0-9]/.test(password)) score += 10;

  if (/^[a-z]+$/.test(password) || /^[0-9]+$/.test(password)) score -= 10;

  
  if (password.length > 12) score += Math.min((password.length - 12) * 2, 20);

  return Math.max(0, Math.min(100, score));
}


export function getPasswordStrengthLabel(score: number): string {
  if (score < 30) return i18n.t('auth:passwordStrength.weak');
  if (score < 50) return i18n.t('auth:passwordStrength.fair');
  if (score < 70) return i18n.t('auth:passwordStrength.good');
  if (score < 90) return i18n.t('auth:passwordStrength.strong');
  return i18n.t('auth:passwordStrength.excellent');
}


export function getPasswordStrengthColor(score: number): string {
  if (score < 30) return 'strength-weak';
  if (score < 50) return 'strength-fair';
  if (score < 70) return 'strength-good';
  return 'strength-strong';
}
