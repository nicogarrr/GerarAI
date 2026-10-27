import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import SettingsSection from '@/components/settings/SettingsSection';
afterEach(() => { window.history.replaceState({}, '', '/'); });
it('keeps form fields mounted in a native closed disclosure', () => {
  render(<SettingsSection id="fiscal" title="Fiscalidad" description="Datos fiscales"><input aria-label="NIF" /></SettingsSection>);
  const input = screen.getByLabelText('NIF');
  expect(input.closest('details')).not.toHaveAttribute('open');
  fireEvent.change(input, {target:{value:'synthetic'}});
  expect(input).toHaveValue('synthetic');
});
it('opens the section on a direct link', () => {
  window.history.replaceState({}, '', '/settings#llm');
  render(<SettingsSection id="llm" title="Modelo de IA" description="Proveedor"><input aria-label="Modelo" /></SettingsSection>);
  expect(screen.getByLabelText('Modelo').closest('details')).toHaveAttribute('open');
});
it('opens after hash navigation without losing edited values', () => {
  render(<SettingsSection id="fiscal" title="Fiscalidad" description="Datos fiscales"><input aria-label="NIF" /></SettingsSection>);
  fireEvent.change(screen.getByLabelText('NIF'), {target:{value:'synthetic'}});
  window.history.replaceState({}, '', '/settings#fiscal');
  fireEvent(window, new HashChangeEvent('hashchange'));
  expect(screen.getByLabelText('NIF').closest('details')).toHaveAttribute('open');
  expect(screen.getByLabelText('NIF')).toHaveValue('synthetic');
});

it('reopens on the same section link after the user closed it', () => {
  window.history.replaceState({}, '', '/settings#llm');
  render(<><a href="#llm">IA</a><SettingsSection id="llm" title="Modelo de IA" description="Proveedor"><input aria-label="Modelo" /></SettingsSection></>);
  const details = screen.getByLabelText('Modelo').closest('details')!;
  details.open = false;
  fireEvent.click(screen.getByRole('link', { name: 'IA' }));
  expect(details).toHaveAttribute('open');
});
