import i18n from './i18n';
import { Link } from 'react-router-dom';
import AdminPageLayout from './components/AdminPageLayout';

export default function AdminHome() {
  const cards = [
    { title: i18n.t('admin:adminHome.content.devices'), desc: i18n.t('admin:adminHome.content.manageDevicesMetadataStatus'), to: '/admin/devices' },
    { title: i18n.t('admin:adminHome.content.dataSources'), desc: i18n.t('admin:adminHome.content.configureExternalDataSourcesSchedules'), to: '/admin/sources' },
    { title: i18n.t('admin:adminHome.content.qcRules'), desc: i18n.t('admin:adminHome.content.reviewManageQaQcRuleSets'), to: '/admin/qc' },
    { title: i18n.t('admin:adminHome.content.emailNotifications'), desc: i18n.t('admin:adminHome.content.configureEmailNotifications'), to: '/admin/email' },
    { title: i18n.t('admin:adminHome.content.csvUpload'), desc: i18n.t('admin:adminHome.content.uploadCsvFileDeviceMeasurements'), to: '/admin/uploads/csv' },
    { title: i18n.t('admin:adminHome.content.events'), desc: i18n.t('admin:adminHome.content.inspectImporterSystemEventLogs'), to: '/admin/events' },
    { title: i18n.t('admin:adminHome.content.users'), desc: i18n.t('admin:adminHome.content.manageUserAccountsRoleAssignments'), to: '/admin/users' },
    { title: i18n.t('admin:adminHome.content.systemPreferences'), desc: i18n.t('admin:adminHome.content.managePlatformWideSettingsSharedService'), to: '/admin/system-preferences' },
  ];

  return (
    <AdminPageLayout
      contentClassName="admin-workspace admin-home-page"
      title={i18n.t('admin:adminHome.tooltips.admin')}
      description={i18n.t('admin:adminHome.accessibility.chooseAreaManage')}
    >
      <div className="admin-home-sections">
        {[{ title: i18n.t('admin:workspace.operations'), cards: cards.slice(0, 6) }, { title: i18n.t('admin:workspace.platform'), cards: cards.slice(6) }].map(group => (
          <section key={group.title}>
            <h2>{group.title}</h2>
            <div className="admin-home-grid">
        {group.cards.map((c) => (
          <Link key={c.to} to={c.to} className="admin-card" style={{ textDecoration: 'none', color: 'inherit' }}>
            <h3 style={{ margin: '0 0 6px 0' }}>{c.title}</h3>
            <p className="muted" style={{ margin: 0 }}>{c.desc}</p>
          </Link>
        ))}
            </div>
          </section>
        ))}
      </div>
    </AdminPageLayout>
  );
}
