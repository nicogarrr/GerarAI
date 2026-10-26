import { build } from 'esbuild';
const repo = '/home/sandbox/gerarai';
await build({
  entryPoints: ['./search-entry.tsx'],
  bundle: true, outfile: '/tmp/fx/search.js', format: 'esm', jsx: 'automatic',
  loader: {'.tsx':'tsx','.ts':'ts','.css':'empty','.png':'empty','.svg':'empty','.json':'json'},
  alias: {
    '@': repo,
    'next/navigation': '/tmp/fx/next-navigation.js',
    'next/link': '/tmp/fx/next-link.jsx',
    '@/lib/actions/finnhub.actions': '/tmp/fx/finnhub-mock.js',
  },
  nodePaths: [repo + '/node_modules'],
});
console.log('built');
