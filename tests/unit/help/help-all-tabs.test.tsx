import {fireEvent, render, screen} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
const support=vi.hoisted(()=>({email:'help@example.invalid'}));
vi.mock('@/lib/config/brand',()=>({get SUPPORT_EMAIL(){return support.email;}}));
import HelpTabs from '@/components/help/HelpTabs';
import {LocaleProvider} from '@/lib/i18n/client';

const activate=(name:string)=>fireEvent.mouseDown(screen.getByRole('tab',{name}),{button:0,ctrlKey:false});
beforeEach(()=>{support.email='help@example.invalid';});
describe('HelpTabs: todos los paneles usan el locale',()=>{
 it.each(['es','en'] as const)('documentación y contacto en %s',(locale)=>{
  const en=locale==='en';
  render(<LocaleProvider locale={locale}><HelpTabs/></LocaleProvider>);
  expect(screen.getByRole('tablist',{name:en?'Help sections':'Secciones de la ayuda'})).toBeInTheDocument();
  activate(en?'Documentation':'Documentación');
  expect(screen.getByRole('heading',{name:en?'First steps: model → thesis → decision':'Primeros pasos: modelo → tesis → decisión'})).toBeInTheDocument();
  expect(screen.getByRole('link',{name:en?'Portfolio':'Cartera'})).toHaveAttribute('href','/portfolio');
  expect(screen.getByRole('link',{name:'/export'})).toHaveAttribute('href','/export');
  expect(screen.getByText(en?'3. Decision.':'3. Decisión.')).toBeInTheDocument();
  expect(screen.getByText(en?'Glossary and methodology':'Glosario y metodología')).toBeInTheDocument();
  expect(screen.queryByText(en?'Primeros pasos: modelo → tesis → decisión':'First steps: model → thesis → decision')).not.toBeInTheDocument();
  activate(en?'Contact':'Contacto');
  expect(screen.getByText(en?'Questions or suggestions? Email us.':'¿Tienes preguntas o sugerencias? Escríbenos por email.')).toBeInTheDocument();
  expect(screen.getByRole('link',{name:new RegExp('help@example.invalid')})).toHaveAttribute('href','mailto:help@example.invalid');
 });
 it.each(['es','en'] as const)('sin dirección de contacto en %s',(locale)=>{
  support.email='';
  render(<LocaleProvider locale={locale}><HelpTabs/></LocaleProvider>);
  activate(locale==='en'?'Contact':'Contacto');
  expect(screen.getByText(locale==='en'?'Questions or suggestions? The contact channel will be published here.':'¿Tienes preguntas o sugerencias? El canal de contacto se publicará aquí.')).toBeInTheDocument();
  expect(screen.queryByRole('link',{name:/Send an email to|Enviar email a/})).not.toBeInTheDocument();
 });
});
