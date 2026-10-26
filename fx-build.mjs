import { build } from 'esbuild';
const repo = '/home/sandbox/gerarai';
await build({
  entryPoints: [repo + '/fx-entry.tsx'],
  bundle: true, outfile: '/tmp/fx/thesis.js', format: 'esm', jsx: 'automatic',
  loader: {'.tsx':'tsx','.ts':'ts','.css':'empty','.png':'empty','.svg':'empty'},
  alias: {
    '@': repo,
    'next/navigation': repo + '/fx-mocks/next-navigation.js',
    'next/link': repo + '/fx-mocks/next-link.jsx',
    '@/lib/actions/thesis-jobs.actions': repo + '/fx-mocks/thesis-jobs.js',
    '@/lib/utils/scroll-anchor': repo + '/fx-mocks/scroll-anchor.js',
  },
});
console.log('built');
