import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ExternalAPI } from './api';
import { useLocation, useParams } from 'react-router-dom';
import AdminPageLayout from './components/AdminPageLayout';
import AdminSources from './AdminSources';

export default function AdminSourceDetail() {
  const params = useParams();
  const id = params?.id ? Number(params.id) : null;
  const location = useLocation();
  const { t } = useTranslation('dataSources');
  const [source, setSource] = useState<ExternalAPI | null>(null);
  const sourceName = source?.external_api_id === id ? source.name : null;

  return (
    <AdminPageLayout
      contentClassName="admin-workspace source-detail-page"
      title={sourceName || t('adminSourceDetail.tooltips.dataSource')}
      breadcrumbs={[
        { label: t('adminSourceDetail.content.admin'), to: '/admin' },
        { label: t('adminSourceDetail.content.dataSources'), to: '/admin/sources' },
        { label: sourceName || t('adminSourceDetail.text.detail') },
      ]}
    >
      <AdminSources
        key={location.key + (location.search || '')}
        onClose={() => {}}
        showTitle={false}
        showSourceHeading={false}
        preselectExternalApiId={id}
        onSourceChange={setSource}
      />
    </AdminPageLayout>
  );
}
