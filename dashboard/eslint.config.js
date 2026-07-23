import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      // caughtErrors: 'none' keeps the ESLint 8 default — `catch (e)` with an
      // unused param is idiomatic here for best-effort try/catch.
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]', caughtErrors: 'none' }],
    },
  },
  {
    // Entry point, context (hook + provider) and modal (helper + component)
    // intentionally mix exports — HMR granularity is not a concern for them.
    files: ['src/main.jsx', 'src/contexts/**/*.jsx', 'src/components/WatermarkModal.jsx'],
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
  {
    // Node context: vite config reads process.env.
    files: ['vite.config.js'],
    languageOptions: {
      globals: globals.node,
    },
  },
])
