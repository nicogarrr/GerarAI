# Interface languages (ES/EN)

Spanish is the default. `gerarai_locale` selects `es` or `en`, without URL prefixes.
`app/layout.tsx` reads the request cookie and supplies the client locale context.
This makes request routes dynamic. There is no process-global locale.

## Messages

Messages live in `messages/<locale>/<area>.json`. The filename supplies the area
prefix, for example `common.json` contains `actions.save`, not `common.actions.save`.
The central registry is `messages/index.ts`. `TranslationKey` follows Spanish leaves.

Use `await getT()` / `await getFormat()` from `lib/i18n/server` in server components.
Use `useT()` / `useFormat()` from `lib/i18n/client` in client components.
The legacy `t()` export remains Spanish while callers migrate.

English areas that are still empty fall back to Spanish. Populated areas must
match Spanish keys and interpolation placeholders; `npm run check:i18n` checks this.
Missing keys or interpolation variables throw in development. Production preserves
unresolved keys or placeholders so evidence of missing copy is not hidden.

Formatters accept an explicit locale or can be bound with `createFormatters(locale)`.
Legacy calls preserve Spanish output. Dates retain their market/user timezones.
Number input parsing uses the selected locale and rejects incompatible syntax.

New orphan keys still fail the guard. Temporary migration reservations are a
finite key list, not exemptions for entire areas. Remove reservations when their
consumers land. Backend field names, tickers, source text and accepted financial
terms are not interface copy and must not be silently translated.
