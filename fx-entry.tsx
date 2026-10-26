import React from 'react';
import { createRoot } from 'react-dom/client';
import ThesisGenerateButton from '@/components/research/ThesisGenerateButton';
const legacy = new URLSearchParams(location.search).has('legacy');
createRoot(document.getElementById('root')!).render(
  <div style={{background:'#101010',padding:24,maxWidth:520,fontFamily:'system-ui'}}>
    <div className="flex flex-wrap items-center gap-3">
      {legacy ? <span className="text-sm text-gray-400">Sin tesis todavía.</span> : null}
      <ThesisGenerateButton ticker="SAN" label="Genera la primera tesis" emptyCopy="Sin tesis todavía." />
    </div>
  </div>
);
