import * as React from 'react';
import { copyToClipboard, formatCoordinates } from '../utils/clipboard';

interface CopyableCoordinatesProps {
  latitude: number | null | undefined;
  longitude: number | null | undefined;
  precision?: number;
  className?: string;
}


const CopyableCoordinates: React.FC<CopyableCoordinatesProps> = ({
  latitude,
  longitude,
  precision = 4,
  className = '',
}) => {
  const [copied, setCopied] = React.useState(false);
  const coordsText = formatCoordinates(latitude, longitude, precision);
  const canCopy = latitude != null && longitude != null;

  const handleClick = React.useCallback(async () => {
    if (!canCopy) return;
    const success = await copyToClipboard(coordsText);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  }, [canCopy, coordsText]);

  const handleKeyDown = React.useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleClick();
    }
  }, [handleClick]);

  return (
    <span
      className={`copyable-coords ${className} ${canCopy ? 'copyable' : ''} ${copied ? 'copied' : ''}`}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      role={canCopy ? 'button' : undefined}
      tabIndex={canCopy ? 0 : undefined}
      title={canCopy ? 'Click to copy coordinates' : undefined}
      aria-label={canCopy ? `Copy coordinates: ${coordsText}` : undefined}
    >
      {copied ? (
        <span className="copied-feedback">Copied!</span>
      ) : (
        coordsText
      )}
    </span>
  );
};

export default CopyableCoordinates;
