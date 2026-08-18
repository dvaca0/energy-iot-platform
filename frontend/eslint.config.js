import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    // Re-enable `no-undef` for the files that opt out of type checking.
    //
    // typescript-eslint's recommended config turns `no-undef` off on purpose:
    // for a type-checked file the compiler already catches undeclared
    // identifiers, and the lint rule misfires on type-only references. That
    // reasoning collapses for a file carrying `@ts-nocheck` — nothing checks
    // it at all. On 2026-08-13 a dangling `effectiveStatus` in App.tsx passed
    // `tsc -b`, passed `eslint`, shipped, and took production down when the
    // branch containing it first executed.
    //
    // Listed explicitly rather than applied globally so the rule stays off
    // where the compiler really is doing the work.
    files: ["src/App.tsx", "src/services/api.ts", "src/components/common.tsx", "src/pages/CostAnalytics.tsx"],
    rules: {
      "no-undef": "error",
    },
  },
])
