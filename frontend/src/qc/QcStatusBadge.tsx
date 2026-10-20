export default function QcStatusBadge({
  tone,
  children,
}: {
  tone: 'recommended' | 'custom' | 'attention' | 'unavailable' | 'neutral';
  children: React.ReactNode;
}) {
  return <span className={`qc-status-badge qc-status-${tone}`}>{children}</span>;
}
