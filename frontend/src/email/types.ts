export type EmailReadinessStatus =
  | 'not_configured'
  | 'disabled'
  | 'needs_attention'
  | 'ready';

export type SmtpSecurityMode = 'starttls' | 'ssl_tls' | 'none';

export interface EmailConfiguration {
  enabled: boolean;
  status: EmailReadinessStatus;
  status_reason_codes: string[];
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_security_mode: SmtpSecurityMode | null;
  smtp_username: string | null;
  password_configured: boolean;
  from_email: string | null;
  from_display_name: string | null;
  reply_to_email: string | null;
  administrator_recipients: string[];
  last_test_status: 'success' | 'failed' | null;
  last_test_error_code: string | null;
  last_tested_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface EmailConfigurationUpdate {
  enabled: boolean;
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_security_mode: SmtpSecurityMode | null;
  smtp_username: string | null;
  smtp_password?: string | null;
  from_email: string | null;
  from_display_name: string | null;
  reply_to_email: string | null;
  administrator_recipients: string[];
}

export interface EmailTestResult {
  delivery_status: 'sent';
  recipient: string;
  sent_at: string;
}

export type AdministratorSummaryCadence = 'daily' | 'hourly' | 'every_15_minutes';

export type AdministratorSummaryScheduleStatus =
  | 'summary_off'
  | 'blocked_email_delivery'
  | 'waiting_for_first_scheduled_period'
  | 'last_summary_sent'
  | 'last_summary_failed'
  | 'delivery_unknown'
  | 'delivery_in_progress';

export interface AdministratorSummaryWindow {
  period_start: string;
  period_end: string;
}

export interface AdministratorSummaryLastDelivery extends AdministratorSummaryWindow {
  status: 'sending' | 'sent' | 'failed' | 'delivery_unknown';
  last_attempted_at: string | null;
  sent_at: string | null;
  error_code: string | null;
}

export interface AdministratorSummaryConfiguration {
  enabled: boolean;
  cadence: AdministratorSummaryCadence;
  daily_send_time: string;
  reporting_timezone: string;
  reporting_timezone_source: 'system_preferences' | 'summary_override';
  reporting_timezone_override: string | null;
  system_timezone: string;
  effective_at: string | null;
  schedule_status: AdministratorSummaryScheduleStatus;
  blocker_codes: string[];
  email_delivery_ready: boolean;
  next_due_at: string | null;
  next_reporting_window: AdministratorSummaryWindow | null;
  last_scheduled_delivery: AdministratorSummaryLastDelivery | null;
}

export interface AdministratorSummaryScheduleUpdate {
  enabled: boolean;
  cadence: AdministratorSummaryCadence;
  daily_send_time: string;
  reporting_timezone_mode: 'system' | 'override';
  reporting_timezone_override: string | null;
}

export interface AdministratorSummaryPreviewOptions {
  cadence?: AdministratorSummaryCadence;
  daily_send_time?: string;
  reporting_timezone_mode?: 'system' | 'override';
  reporting_timezone_override?: string | null;
}

export interface AdministratorSummaryPreview {
  reporting_window: AdministratorSummaryWindow;
  overall_status: 'all_systems_normal' | 'needs_attention';
  attention_count: number;
  subject: string;
  html_body: string;
  text_body: string;
}

export interface AdministratorSummaryTestOptions extends AdministratorSummaryPreviewOptions {
  recipient?: string;
}

export interface AdministratorSummaryTestResult {
  delivery_status: 'sent';
  recipient: string;
  sent_at: string;
  subject: string;
  reporting_window: AdministratorSummaryWindow;
}
