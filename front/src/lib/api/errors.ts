/** The uniform error envelope every `/v1` failure returns. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    request_id?: string;
  };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId?: string;

  constructor(status: number, body: ApiErrorBody | undefined, fallbackMessage: string) {
    super(body?.error?.message ?? fallbackMessage);
    this.name = 'ApiError';
    this.status = status;
    this.code = body?.error?.code ?? 'UNKNOWN';
    this.details = body?.error?.details ?? {};
    this.requestId = body?.error?.request_id;
  }

  /** Field-level validation messages, keyed by field name. */
  get fieldErrors(): Record<string, string> {
    const fields = this.details.fields;
    if (!fields || typeof fields !== 'object') return {};
    return Object.fromEntries(
      Object.entries(fields as Record<string, unknown>).map(([key, value]) => [key, String(value)]),
    );
  }

  get isAuthRequired(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  get isInsufficientCredits(): boolean {
    return this.code === 'INSUFFICIENT_CREDITS';
  }

  get isRateLimited(): boolean {
    return this.status === 429;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}
