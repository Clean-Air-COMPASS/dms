import React from 'react';
import i18n from '../i18n';



export interface DataSourceBadgeProps {
  
  source?: string | null;
  
  size?: 'sm' | 'md' | 'lg';
  
  showIcon?: boolean;
  
  className?: string;
}


const SOURCE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  openaq: { bg: '#e0f2fe', text: '#0369a1', border: '#7dd3fc' },
  purpleair: { bg: '#fae8ff', text: '#a21caf', border: '#e879f9' },
  airgradient: { bg: '#dcfce7', text: '#15803d', border: '#86efac' },
  csv: { bg: '#fef3c7', text: '#92400e', border: '#fcd34d' },
  manual: { bg: '#f3f4f6', text: '#4b5563', border: '#d1d5db' },
  default: { bg: '#f0f9ff', text: '#064789', border: '#bae6fd' },
};


const SOURCE_ICONS: Record<string, string> = {
  openaq: '🌐',
  purpleair: '💜',
  airgradient: '🌿',
  csv: '📄',
  manual: '✏️',
  default: '📡',
};

const DataSourceBadge: React.FC<DataSourceBadgeProps> = ({
  source,
  size = 'md',
  showIcon = true,
  className = '',
}) => {
  if (!source) return null;

  const normalizedSource = source.toLowerCase().replace(/[^a-z0-9]/g, '');
  const colors = SOURCE_COLORS[normalizedSource] || SOURCE_COLORS.default;
  const icon = showIcon ? (SOURCE_ICONS[normalizedSource] || SOURCE_ICONS.default) : null;

  const sizeClasses: Record<string, string> = {
    sm: 'data-source-badge--sm',
    md: 'data-source-badge--md',
    lg: 'data-source-badge--lg',
  };

  return (
    <span
      className={`data-source-badge ${sizeClasses[size]} ${className}`}
      style={{
        backgroundColor: colors.bg,
        color: colors.text,
        borderColor: colors.border,
      }}
      title={i18n.t('common:dynamic.dataSource', { source })}
    >
      {icon && <span className="data-source-badge__icon" aria-hidden="true">{icon}</span>}
      <span className="data-source-badge__text">{source}</span>
    </span>
  );
};

export default DataSourceBadge;
