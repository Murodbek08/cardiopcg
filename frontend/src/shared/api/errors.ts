import { AxiosError } from 'axios';

export interface FieldError {
  field: string;
  msg: string;
  type?: string;
}

/** Backend error envelope: { error: { code, message, details[], request_id } } (doc 01, section 0). */
export interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    details?: FieldError[] | Record<string, unknown> | null;
    request_id?: string;
  };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly fieldErrors: FieldError[];
  readonly details?: Record<string, unknown>;
  readonly retryAfter?: number;
  readonly isNetwork: boolean;

  constructor(init: {
    status: number;
    code: string;
    message: string;
    requestId?: string;
    fieldErrors?: FieldError[];
    details?: Record<string, unknown>;
    retryAfter?: number;
    isNetwork?: boolean;
  }) {
    super(init.message);
    this.name = 'ApiError';
    this.status = init.status;
    this.code = init.code;
    this.requestId = init.requestId;
    this.fieldErrors = init.fieldErrors ?? [];
    this.details = init.details;
    this.retryAfter = init.retryAfter;
    this.isNetwork = init.isNetwork ?? false;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

/** Turns any thrown value (axios error, blob error, unknown) into an ApiError. */
export function normalizeError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (error instanceof AxiosError) {
    const res = error.response;
    if (!res) {
      const canceled = error.code === 'ERR_CANCELED';
      return new ApiError({
        status: 0,
        code: canceled ? 'CANCELED' : 'NETWORK_ERROR',
        message: canceled ? 'Bekor qilindi' : 'Tarmoq xatosi',
        isNetwork: !canceled,
      });
    }
    const body = (res.data ?? {}) as ErrorEnvelope;
    const env = body.error ?? {};
    const details = env.details;
    const fieldErrors = Array.isArray(details) ? details : [];
    const retryHeader = Number(res.headers?.['retry-after']);
    return new ApiError({
      status: res.status,
      code: env.code ?? `HTTP_${res.status}`,
      message: env.message ?? error.message,
      requestId: env.request_id ?? (res.headers?.['x-request-id'] as string | undefined),
      fieldErrors,
      details: details && !Array.isArray(details) ? (details as Record<string, unknown>) : undefined,
      retryAfter: Number.isFinite(retryHeader) && retryHeader > 0 ? retryHeader : undefined,
    });
  }
  const message = error instanceof Error ? error.message : 'Noma\'lum xato';
  return new ApiError({ status: 0, code: 'UNKNOWN', message });
}

/** Maps the first-level field errors to a { field: message } record for react-hook-form. */
export function fieldErrorMap(e: ApiError): Record<string, string> {
  const out: Record<string, string> = {};
  for (const fe of e.fieldErrors) {
    const key = fe.field.replace(/^body\./, '');
    out[key] = fe.msg;
  }
  return out;
}
