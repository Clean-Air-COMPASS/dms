import { Link } from 'react-router-dom';
import AdminPageLayout from './components/AdminPageLayout';

export default function AdminHome() {
  const cards = [
    { title: 'Devices', desc: 'Manage devices, metadata, and status.', to: '/admin/devices' },
    { title: 'QC Rules', desc: 'Review and manage QA/QC rule sets.', to: '/admin/qc' },
    { title: 'Data Sources', desc: 'Configure external data sources and schedules.', to: '/admin/sources' },
    { title: 'CSV Upload', desc: 'Upload a CSV file with device measurements.', to: '/admin/uploads/csv' },
    { title: 'System Preferences', desc: 'Manage platform-wide settings and shared service keys.', to: '/admin/system-preferences' },
    { title: 'Users', desc: 'Manage user accounts and role assignments.', to: '/admin/users' },
    { title: 'Events', desc: 'Inspect importer and system event logs.', to: '/admin/events' },
  ];

  return (
    <AdminPageLayout
      title="Admin"
      description="Choose an area to manage."
    >
      <div className="card admin-home-grid">
        {cards.map((c) => (
          <Link key={c.to} to={c.to} className="admin-card" style={{ textDecoration: 'none', color: 'inherit' }}>
            <h3 style={{ margin: '0 0 6px 0' }}>{c.title}</h3>
            <p className="muted" style={{ margin: 0 }}>{c.desc}</p>
          </Link>
        ))}
      </div>
    </AdminPageLayout>
  );
}
