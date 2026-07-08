/**
 * Service REST API 客户端。
 * 开发环境通过 vite proxy 转发到 :8001（见 vite.config.ts）。
 * 业务路由统一走 /api/v1 前缀；/health 等根路径用 apiRoot。
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    throw new Error(`${resp.status} ${resp.statusText}`)
  }
  return resp.json() as Promise<T>
}

const BASE = '/api/v1'

const json = (body?: unknown) => (body ? JSON.stringify(body) : undefined)

export const api = {
  get: <T>(path: string) => request<T>(`${BASE}${path}`),
  post: <T>(path: string, body?: unknown) =>
    request<T>(`${BASE}${path}`, { method: 'POST', body: json(body) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(`${BASE}${path}`, { method: 'PUT', body: json(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(`${BASE}${path}`, { method: 'PATCH', body: json(body) }),
  delete: <T>(path: string) => request<T>(`${BASE}${path}`, { method: 'DELETE' }),
}

/** 根路径请求（/health 等），不走 /api/v1 前缀。 */
export const apiRoot = {
  get: <T>(path: string) => request<T>(path),
}
