import type { Page } from '@playwright/test';

export const stamp = '2026-09-05T09:30:00Z';
const user = { user_id: 'review-admin', email: 'administrator@example.org', roles: ['admin'], scopes: ['users:write'], is_active: true, created_at: stamp, updated_at: stamp };
const device = { device_id: 123, name: 'Central community monitoring station', friendly_name: 'Central Library', external_id: 'station-central-library-123456789', external_api_id: 1, external_api_name: 'OpenAQ', network: 'OpenAQ', status: 'active', latitude: 38.44, longitude: -122.71, timezone: 'America/Los_Angeles', allow_updates: 'inherit', is_external: true, created_at: stamp, last_seen_at: stamp };
const sources = ['OpenAQ', 'PurpleAir', 'AirGradient'].map((name, index) => ({ external_api_id: index + 1, name, provider_code: name.toLowerCase(), base_url: `https://api.${name.toLowerCase()}.com`, description: `${name} measurement provider`, enabled: true, has_api_key: index !== 2, is_configured: index !== 2, is_runnable: index !== 2, runnable_reason: index === 2 ? 'configuration_required' : 'ready', is_builtin: true, can_delete: false, device_count: 4, params: {} }));

export async function mockAdministration(page: Page, language = 'en') {
  const state = {
    device: { ...device }, sources: structuredClone(sources),
    preferences: { geoapify_api_key: '', default_language_code: 'en', system_timezone: 'UTC', updated_at: stamp, last_updated_by_email: user.email, storage: { free_bytes: 80000000000, used_bytes: 20000000000, total_bytes: 100000000000, percent_free: 80, status: 'healthy' } },
    email: { enabled: true, status: 'ready', status_reason_codes: [], smtp_host: 'smtp.example.org', smtp_port: 587, smtp_security_mode: 'starttls', smtp_username: 'notifications@example.org', password_configured: true, from_email: 'notifications@example.org', from_display_name: 'CompassAQ', reply_to_email: null, administrator_recipients: ['administrator@example.org'], last_test_status: 'success', last_test_error_code: null, last_tested_at: stamp, created_at: stamp, updated_at: stamp },
    summary: { enabled: false, cadence: 'daily', daily_send_time: '07:00:00', reporting_timezone: 'UTC', reporting_timezone_source: 'system_preferences', reporting_timezone_override: null, system_timezone: 'UTC', effective_at: null, schedule_status: 'summary_off', blocker_codes: [], email_delivery_ready: true, next_due_at: null, next_reporting_window: null, last_scheduled_delivery: null },
    writes: [] as string[],
  };
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, '');
    let body: unknown = [];
    if (!['GET', 'HEAD'].includes(request.method())) state.writes.push(path);
    if (path === '/health/readiness') body = { status: 'ready' };
    else if (path === '/setup/status') body = { is_setup_required: false, has_users: true, default_language_code: language };
    else if (path === '/auth/refresh') body = { access_token: 'fixture-session' };
    else if (path === '/auth/me') body = { ...user, preferred_language_code: language, system_default_language_code: language };
    else if (path === '/admin/users') body = [user];
    else if (path === '/admin/external_apis') body = state.sources;
    else if (/\/external_apis\/\d+\/schedules$/.test(path)) body = [{ job_schedule_id: 1, task: 'openaq_import', cron_expr: '0 * * * *', timezone: 'UTC', enabled: false, allow_overlap: false }];
    else if (path === '/admin/jobs/schedules/1') body = { job_schedule_id: 1, task: 'openaq_import', ...request.postDataJSON() };
    else if (path === '/admin/imports/run') body = { status: 'success', devices_processed: 4, measurements_inserted: 20 };
    else if (path === '/admin/devices/purpleair/lookup') body = { device, sensors: [{ external_sensor_id: '77', parameter_code: 'pm25', latest_value: 12.5, unit_code: 'ug_m3' }] };
    else if (path === '/admin/devices/purpleair/create') body = { device, sensors: [] };
    else if (path.startsWith('/admin/devices/openaq/lookup')) body = { locations: [{ device: { ...device, external_id: '456' }, sensors: [{ sensor_id: 77, parameter_code: 'pm25', parameter_name: 'PM2.5', unit: 'µg/m³', exists: false }], already_exists: false, metadata: {} }] };
    else if (path === '/admin/devices/openaq/create') body = { count: 1, created: [{ device, sensors: [] }] };
    else if (/^\/admin\/external_apis\/\d+$/.test(path)) {
      const source = state.sources.find(item => item.external_api_id === Number(path.split('/').pop()))!;
      if (request.method() === 'PUT') {
        Object.assign(source, request.postDataJSON());
        source.is_runnable = source.enabled && source.is_configured;
        source.runnable_reason = !source.enabled ? 'disabled' : source.is_configured ? 'ready' : 'configuration_required';
      }
      body = source;
    } else if (path === '/admin/devices') {
      if (request.method() === 'POST') { Object.assign(state.device, request.postDataJSON(), { is_external: false }); body = state.device; }
      else body = !url.searchParams.get('name') || state.device.friendly_name.toLowerCase().includes(url.searchParams.get('name')!.toLowerCase()) ? [state.device, { ...device, device_id: 124, friendly_name: 'Riverside', status: 'unknown', last_seen_at: null }] : [];
    } else if (path === '/admin/devices/123') {
      if (request.method() === 'PUT') Object.assign(state.device, request.postDataJSON());
      body = state.device;
    } else if (/\/devices\/123\/sensors/.test(path)) body = [{ sensor_id: 77, parameter_code: 'pm25', parameter_name: 'PM2.5', aggregation_code: '1h', external_sensor_id: 'central-library-pm25-hourly-77', value: 12.5, unit_symbol: 'µg/m³', observed_at: stamp, is_valid: true }];
    else if (path === '/parameters') body = [{ parameter_id: 1, code: 'pm25', display_name: 'PM2.5' }];
    else if (path === '/aggregation_periods') body = [{ code: '1h', display_name: 'Hourly' }];
    else if (path === '/admin/system-preferences') {
      if (request.method() === 'PUT') Object.assign(state.preferences, request.postDataJSON());
      body = state.preferences;
    } else if (path === '/admin/email/configuration') {
      if (request.method() === 'PUT') Object.assign(state.email, request.postDataJSON());
      body = state.email;
    } else if (path === '/admin/email/administrator-summary') {
      if (request.method() === 'PUT') Object.assign(state.summary, request.postDataJSON());
      body = state.summary;
    } else if (path === '/admin/email/test') body = { success: true, recipient: 'administrator@example.org' };
    else if (path === '/admin/jobs/runs') body = [{ job_run_id: 41, job_schedule_id: 1, task: 'openaq_import', status: 'success', started_at: stamp, finished_at: stamp, duration_seconds: 12, summary: { devices_processed: 4, sensors_processed: 8, measurements_received: 24, measurements_inserted: 20, measurements_skipped: 4 } }];
    else if (path === '/admin/events') body = [{ event_id: 9, event_type: 'import.completed', source: 'openaq_import', severity: 'info', created_at: stamp, timestamp: stamp, message: 'Import completed. Four devices checked; existing measurements were preserved.', actor_email: user.email, device_id: 123, sensor_id: 77 }];
    else if (path === '/admin/events/qc-failures') body = { items: [], total: 0, limit: 25, offset: 0 };
    else if (path === '/admin/qc/parameters') body = { items: [], total: 0, default_profile_version: 'compassaq-default-v1' };
    else if (path === '/admin/qc/checks') body = { items: [] };
    else if (path === '/admin/imports/upload-csv') body = { success: false, message: 'One row could not be imported.', total_records: 2, inserted_records: 1, failed_records: 1, errors: ['Row 3: Unknown sensor 999999'] };
    await route.fulfill({ json: body });
  });
  return state;
}
