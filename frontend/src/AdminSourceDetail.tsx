import { useLocation, useParams } from 'react-router-dom';
import AdminPageLayout from './components/AdminPageLayout';
import AdminSources from './AdminSources';

export default function AdminSourceDetail() {
  const params = useParams();
  const id = params?.id ? Number(params.id) : null;
  const location = useLocation();

  return (
    <AdminPageLayout
      title="Data Source"
      breadcrumbs={[
        { label: 'Admin', to: '/admin' },
        { label: 'Data Sources', to: '/admin/sources' },
        { label: id ? `Source ${id}` : 'Detail' },
      ]}
    >
      <AdminSources
        key={location.key + (location.search || '')}
        onClose={() => {}}
        showTitle={false}
        preselectExternalApiId={id}
      />
    </AdminPageLayout>
  );
}
