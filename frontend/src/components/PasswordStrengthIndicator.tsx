

import { useMemo } from 'react';
import {
  validatePasswordStrength,
  getPasswordStrengthScore,
  getPasswordStrengthLabel,
  getPasswordStrengthColor,
} from '../utils/passwordStrength';

interface PasswordStrengthIndicatorProps {
  password: string;
  email?: string;
  
  showChecklist?: boolean;
  
  showMeter?: boolean;
}

export default function PasswordStrengthIndicator({
  password,
  email,
  showChecklist = true,
  showMeter = true,
}: PasswordStrengthIndicatorProps) {
  const result = useMemo(
    () => validatePasswordStrength(password, email),
    [password, email]
  );

  const score = useMemo(() => getPasswordStrengthScore(password), [password]);
  const strengthLabel = getPasswordStrengthLabel(score);
  const strengthColor = getPasswordStrengthColor(score);

  
  if (!password) {
    return null;
  }

  return (
    <div className="password-strength-indicator">
      
      {showMeter && (
        <div className="password-strength-meter">
          <div className="password-strength-bar-bg">
            <div
              className={`password-strength-bar-fill ${strengthColor}`}
              style={{ width: `${score}%` }}
              role="progressbar"
              aria-valuenow={score}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`Password strength: ${strengthLabel}`}
            />
          </div>
          <span className={`password-strength-label ${strengthColor}`}>
            {strengthLabel}
          </span>
        </div>
      )}

      
      {showChecklist && (
        <ul className="password-strength-checklist" aria-label="Password requirements">
          {result.checks.map((check) => (
            <li
              key={check.key}
              className={`password-check-item ${check.passed ? 'passed' : 'failed'}`}
            >
              <span className="password-check-icon" aria-hidden="true">
                {check.passed ? '✓' : '○'}
              </span>
              <span className="password-check-label">{check.label}</span>
            </li>
          ))}
        </ul>
      )}

      
      {result.warning && result.isValid && (
        <p className="password-strength-warning">{result.warning}</p>
      )}
    </div>
  );
}
