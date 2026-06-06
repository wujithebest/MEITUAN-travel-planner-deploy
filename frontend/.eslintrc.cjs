module.exports = {
  root: true,
  env: {
    browser: true,
    es2022: true,
    node: true,
  },
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: {
      jsx: true,
    },
  },
  plugins: ['@typescript-eslint', 'react-hooks'],
  extends: ['eslint:recommended'],
  ignorePatterns: ['dist', 'node_modules', 'src/types/*.d.ts'],
  globals: {
    AMap: 'readonly',
    EventListener: 'readonly',
    NodeJS: 'readonly',
  },
  rules: {
    'no-unused-vars': 'off',
    'no-case-declarations': 'off',
    'no-constant-condition': 'off',
    'no-useless-escape': 'off',
    'react-hooks/rules-of-hooks': 'error',
  },
  overrides: [
    {
      files: ['src/__tests__/**/*.{ts,tsx}'],
      env: {
        jest: true,
      },
    },
  ],
};
