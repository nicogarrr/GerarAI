import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const eslintConfig = [
  // Next omits .cjs from its JS preset, while our policy overrides apply
  // globally. Include CommonJS in the preset too, with the same plugins and
  // rules: never disable the hook policy or silently ignore browser tests.
  ...nextVitals.map((config) => config.files && config.plugins?.["react-hooks"]
    ? { ...config, files: [...config.files, "**/*.cjs"] }
    : config),
  ...nextTypescript,
  {
    ignores: [
      "node_modules/**",
      "qa-e2e/**",
      ".next/**",
      ".next-*/**",
      ".next-e2e/**",
      "playwright-report/**",
      "test-results/**",
      "data-engine/.pytest_cache/**",
      "data-engine/.venv/**",
      "data-engine/**/__pycache__/**",
      "data-engine/**/*.py",
      "data-engine/**/*.html",
      "data-engine/**/*.db",
      "data-engine/storage/**",
      "out/**",
      "build/**",
      "dist/**",
      "next-env.d.ts",
      "**/*.d.ts",
      "**/*.config.*",
    ],
  },
  {
    rules: {
      // Standard convention: intentionally-omitted identifiers use a leading
      // underscore (destructured-rest siblings are deliberate omissions).
      "@typescript-eslint/no-unused-vars": [
        "warn",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
          ignoreRestSiblings: true,
        },
      ],
      "@typescript-eslint/no-explicit-any": "warn",
      "react-hooks/error-boundaries": "warn",
      "react-hooks/purity": "warn",
      "react-hooks/set-state-in-effect": "warn",
      "react/no-unescaped-entities": "warn",
    },
  },
];

export default eslintConfig;
