import i18n from './i18n';

export type ApiErrorContext = Record<string, string | number | boolean | null>;

export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string | null;
  readonly errorContext: ApiErrorContext;
  readonly diagnosticMessage: string | null;

  constructor(options: {
    status: number;
    errorCode?: string | null;
    errorContext?: ApiErrorContext;
    diagnosticMessage?: string | null;
  }) {
    super(i18n.t('common:errors.requestFailed'));
    this.name = 'ApiError';
    this.status = options.status;
    this.errorCode = options.errorCode ?? null;
    this.errorContext = options.errorContext ?? {};
    this.diagnosticMessage = options.diagnosticMessage ?? null;
  }
}

type ErrorDetail = {
  error_code?: unknown;
  reason_code?: unknown;
  error_context?: unknown;
  reason?: unknown;
  message?: unknown;
};

function isContext(value: unknown): value is ApiErrorContext {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  let errorCode: string | null = null;
  let errorContext: ApiErrorContext = {};
  let diagnosticMessage: string | null = null;

  try {
    const body = await response.json() as { detail?: unknown };
    if (typeof body.detail === 'string') {
      diagnosticMessage = body.detail;
    } else if (body.detail && typeof body.detail === 'object') {
      const detail = body.detail as ErrorDetail;
      if (typeof detail.error_code === 'string') errorCode = detail.error_code;
      else if (typeof detail.reason_code === 'string') errorCode = detail.reason_code;
      else if (typeof detail.reason === 'string') errorCode = detail.reason;
      if (isContext(detail.error_context)) errorContext = detail.error_context;
      if (typeof detail.message === 'string') diagnosticMessage = detail.message;
    }
  } catch {
    diagnosticMessage = response.statusText || null;
  }

  return new ApiError({
    status: response.status,
    errorCode,
    errorContext,
    diagnosticMessage,
  });
}
