
import { useParams, useLocation } from 'react-router-dom';
import AdminPageLayout from './components/AdminPageLayout';
import AdminSources from './AdminSources';

export default function AdminSourcePurpleAir() {
  const params = useParams();
  const id = params?.id ? Number(params.id) : null;
  const location = useLocation();
  return (
    <AdminPageLayout
      title="PurpleAir"
      breadcrumbs={[
        { label: 'Admin', to: '/admin' },
        { label: 'Data Sources', to: '/admin/sources' },
        { label: 'PurpleAir' },
      ]}
    >
      <AdminSources key={location.key + (location.search || '')} onClose={() => {}} showTitle={false} forceSourceName={"PurpleAir"} preselectExternalApiId={id} />
    </AdminPageLayout>
  );
}
