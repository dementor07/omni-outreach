/**
 * ESLint config for the Omni n8n community node package.
 * Uses eslint-plugin-n8n-nodes-base to enforce the community-node conventions
 * n8n's verified-publisher checks expect.
 */
module.exports = {
  root: true,
  env: {
    browser: true,
    es6: true,
    node: true,
  },
  parser: '@typescript-eslint/parser',
  parserOptions: {
    project: ['./tsconfig.json'],
    sourceType: 'module',
    extraFileExtensions: ['.json'],
  },
  ignorePatterns: ['.eslintrc.js', '**/*.js', '**/node_modules/**', '**/dist/**'],
  overrides: [
    {
      files: ['package.json'],
      // package.json is JSON, not a TS project file — don't run the typed parser
      // over it (it isn't in tsconfig's include), just the n8n community rules.
      parserOptions: { project: null },
      plugins: ['eslint-plugin-n8n-nodes-base'],
      extends: ['plugin:n8n-nodes-base/community'],
      rules: {
        'n8n-nodes-base/community-package-json-name-still-default': 'off',
      },
    },
    {
      files: ['./credentials/**/*.ts'],
      plugins: ['eslint-plugin-n8n-nodes-base'],
      extends: ['plugin:n8n-nodes-base/credentials'],
      rules: {
        // This rule's autofix mangles a valid documentationUrl string into
        // camelCase (a plugin bug in this version); the property name itself is
        // the correct n8n API. documentationUrl is cosmetic metadata — disable
        // the mis-firing check rather than ship a broken URL.
        'n8n-nodes-base/cred-class-field-documentation-url-miscased': 'off',
        'n8n-nodes-base/cred-class-field-documentation-url-not-http-url': 'off',
      },
    },
    {
      files: ['./nodes/**/*.ts'],
      plugins: ['eslint-plugin-n8n-nodes-base'],
      extends: ['plugin:n8n-nodes-base/nodes'],
    },
  ],
}
