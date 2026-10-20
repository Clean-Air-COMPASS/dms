import { Trans } from 'react-i18next';
import { Link } from 'react-router-dom';
import UserMenu from './UserMenu';
import '../admin/admin.css';



export interface BreadcrumbItem {
  label: string;
  to?: string;
}

export interface AdminPageLayoutProps {
  
  title: string;
  
  description?: string;
  
  breadcrumbs?: BreadcrumbItem[];
  
  actions?: React.ReactNode;
  
  children: React.ReactNode;
  
  contentClassName?: string;
  
  hidePageHeader?: boolean;
}

export default function AdminPageLayout({
  title,
  description,
  breadcrumbs,
  actions,
  children,
  contentClassName,
  hidePageHeader,
}: AdminPageLayoutProps) {
  return (
    <div className="app-root admin-page">
      
      <div className="page-header">
        <Link to="/map" className="overlay-title" style={{ textDecoration: 'none', color: 'inherit' }}>
          COMPASS
        </Link>
        <div className="row-flex header-spacer gap-8">
          <Link className="btn" to="/map"><Trans ns="admin" i18nKey="adminPageLayout.actions.map" /></Link>
          <Link className="btn" to="/analytics"><Trans ns="admin" i18nKey="adminPageLayout.actions.analytics" /></Link>
        </div>
        <UserMenu />
      </div>

      
      <div className="page-content">
        <div className={`admin-page-content${contentClassName ? ` ${contentClassName}` : ''}`}>
          {!hidePageHeader && (
            <div className="admin-page-header">
              <div>
                
                {breadcrumbs && breadcrumbs.length > 0 && (
                  <div className="breadcrumbs">
                    {breadcrumbs.map((crumb, index) => (
                      <span key={index}>
                        {crumb.to ? (
                          <Link to={crumb.to}>{crumb.label}</Link>
                        ) : (
                          <span>{crumb.label}</span>
                        )}
                        {index < breadcrumbs.length - 1 && (
                          <span aria-hidden="true">/</span>
                        )}
                      </span>
                    ))}
                  </div>
                )}

                
                <h1>{title}</h1>

                
                {description && <p className="muted">{description}</p>}
              </div>

              
              {actions && (
                <div className="admin-page-actions">
                  {actions}
                </div>
              )}
            </div>
          )}

          
          {children}
        </div>
      </div>
    </div>
  );
}
