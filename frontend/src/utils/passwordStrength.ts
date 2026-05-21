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
    label: `At least ${minLength} characters`,
    passed: password.length >= minLength,
  });

  
  checks.push({
    key: 'uppercase',
    label: 'At least one uppercase letter',
    passed: /[A-Z]/.test(password),
  });

  
  checks.push({
    key: 'lowercase',
    label: 'At least one lowercase letter',
    passed: /[a-z]/.test(password),
  });

  
  checks.push({
    key: 'number',
    label: 'At least one number',
    passed: /[0-9]/.test(password),
  });

  
  checks.push({
    key: 'special',
    label: 'At least one special character',
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
    label: 'Does not contain your email',
    passed: !containsEmail,
  });

  const isValid = checks.every((c) => c.passed);

  
  let warning: string | undefined;
  if (isValid && password.length < 16) {
    warning = 'Consider using a longer password for better security.';
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
  if (score < 30) return 'Weak';
  if (score < 50) return 'Fair';
  if (score < 70) return 'Good';
  if (score < 90) return 'Strong';
  return 'Excellent';
}


export function getPasswordStrengthColor(score: number): string {
  if (score < 30) return 'strength-weak';
  if (score < 50) return 'strength-fair';
  if (score < 70) return 'strength-good';
  return 'strength-strong';
}
