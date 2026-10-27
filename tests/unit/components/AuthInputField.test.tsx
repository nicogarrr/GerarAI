import { fireEvent, render, screen } from '@testing-library/react';
import { useForm } from 'react-hook-form';
import { describe, expect, it } from 'vitest';
import InputField from '@/components/forms/InputField';

function Field({ name = 'password', type = 'password', disabled = false }) {
    const { register } = useForm({ defaultValues: { password: '', email: '', totpCode: '' } });
    return <InputField name={name} label={name} placeholder={name} type={type} register={register} disabled={disabled} />;
}

describe('Auth input ergonomics', () => {
    it('toggles visibility without losing the password, submitting or changing autocomplete', () => {
        render(<Field />);
        const field = screen.getByLabelText('password');
        fireEvent.change(field, { target: { value: 'test-password' } });
        const button = screen.getByRole('button', { name: 'Mostrar contraseña' });
        expect(button).toHaveAttribute('type', 'button');
        fireEvent.click(button);
        expect(field).toHaveAttribute('type', 'text');
        expect(field).toHaveValue('test-password');
        expect(field).toHaveAttribute('autocomplete', 'current-password');
        expect(button).toHaveAttribute('aria-pressed', 'true');
        fireEvent.click(screen.getByRole('button', { name: 'Ocultar contraseña' }));
        expect(field).toHaveAttribute('type', 'password');
        expect(field).toHaveValue('test-password');
    });
    it('does not offer a password toggle for email and prevents capitalization', () => {
        render(<Field name="email" type="text" />);
        expect(screen.queryByRole('button')).not.toBeInTheDocument();
        expect(screen.getByLabelText('email')).toHaveAttribute('inputmode', 'email');
        expect(screen.getByLabelText('email')).toHaveAttribute('autocapitalize', 'none');
    });
    it('offers the numeric keyboard for 2FA', () => {
        render(<Field name="totpCode" type="text" />);
        expect(screen.getByLabelText('totpCode')).toHaveAttribute('inputmode', 'numeric');
    });
    it('keeps disabled inputs and toggle disabled', () => {
        render(<Field disabled />);
        expect(screen.getByLabelText('password')).toBeDisabled();
        expect(screen.getByRole('button')).toBeDisabled();
    });
});
