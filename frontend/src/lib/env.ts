const rawApi = import.meta.env.VITE_API_BASE_URL?.trim()
const rawMocks = import.meta.env.VITE_USE_MOCKS?.trim()

/**
 * Runtime configuration, resolved once at module load.
 *
 * - `apiBaseUrl` defaults to the local FastAPI dev server.
 * - `useMocks` defaults to the in-browser mock backend during `vite dev` and is
 *   off for production builds, unless `VITE_USE_MOCKS` overrides it explicitly.
 */
export const env = {
  apiBaseUrl: (rawApi && rawApi.length > 0 ? rawApi : 'http://localhost:8000').replace(/\/+$/, ''),
  useMocks: rawMocks ? rawMocks === 'true' : import.meta.env.DEV,
} as const
