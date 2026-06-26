/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the EchoAssist FastAPI backend (no trailing slash). */
  readonly VITE_API_BASE_URL?: string
  /** "true" to serve the dashboard from the in-browser mock backend (MSW). */
  readonly VITE_USE_MOCKS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
