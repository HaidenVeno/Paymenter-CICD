// Flat ESLint config for security scanning of Paymenter's first-party JS.
// Scope (confirmed in Lab 4 s3.2): only themes/default/js/*.js is first-party;
// everything under public/js is bundled third-party and out of scope.
import security from 'eslint-plugin-security';

export default [
  security.configs.recommended,
  {
    files: ['**/*.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
    },
    rules: {
      // The two rules Lab 4 explicitly checked, promoted to errors so a
      // regression fails CI.
      'security/detect-eval-with-expression': 'error',
      'security/detect-non-literal-fs-filename': 'error',
    },
  },
];
