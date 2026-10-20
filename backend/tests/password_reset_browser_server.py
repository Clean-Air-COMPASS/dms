"""Disposable PostgreSQL API for the real Playwright reset/login workflow.

Run with COMPASSAQ_POSTGRES_TEST_URL set. COMPASSAQ_APPLICATION_URL is optional;
omit it to test browser-origin resolution through the normal same-origin proxy.
The database is created for this process and removed when it exits normally.
"""
import os
import uuid

from postgresql_test_support import temporary_postgres_database, upgrade


def main():
    os.environ['COMPASSAQ_ENV'] = 'test'
    os.environ['DISABLE_PAID_API_REQUESTS'] = 'true'
    os.environ['JWT_SECRET_KEY'] = 'isolated-browser-test-secret-at-least-32-characters'
    with temporary_postgres_database('reset_browser') as (url, engine):
        upgrade(url, 'head')
        os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
        from sqlalchemy.orm import Session
        from models import Role, User, UserRole
        from services.auth import hash_password
        from services.system_settings import get_or_create_system_settings
        from sqlalchemy import select
        with Session(engine) as session:
            org = uuid.uuid4()
            for email, role_name in [('browser-admin@example.org', 'admin'), ('browser-staff@example.org', 'analyst')]:
                role = session.scalar(select(Role).where(Role.name == role_name))
                if role is None:
                    role = Role(role_id=uuid.uuid4(), name=role_name)
                    session.add(role)
                    session.flush()
                user = User(user_id=uuid.uuid4(), org_id=org, email=email, password_hash=hash_password('BrowserOriginalCredential123!'), is_active=True)
                session.add(user)
                session.flush()
                session.add(UserRole(user_id=user.user_id, role_id=role.role_id))
            get_or_create_system_settings(session).is_system_setup_complete = True
            session.commit()
        from api.main import app
        import uvicorn
        uvicorn.run(app, host='0.0.0.0', port=8000, access_log=False)


if __name__ == '__main__':
    main()
