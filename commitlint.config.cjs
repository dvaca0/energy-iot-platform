/**
 * Conventional Commits, enforced in CI.
 *
 *   feat(monitoring): add phase imbalance rule
 *   fix(edge): clamp counter delta across a meter reset
 *
 * See CONTRIBUTING.md.
 */
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      [
        'feat',
        'fix',
        'docs',
        'style',
        'refactor',
        'perf',
        'test',
        'build',
        'ci',
        'chore',
        'revert',
      ],
    ],
    'scope-enum': [
      1,
      'always',
      ['backend', 'frontend', 'edge', 'monitoring', 'db', 'docs', 'ci', 'deps', 'assets', 'tests'],
    ],
    'subject-case': [2, 'never', ['start-case', 'pascal-case', 'upper-case']],
    'header-max-length': [2, 'always', 72],
    'body-max-line-length': [1, 'always', 100],
  },
};
