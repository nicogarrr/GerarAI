import React from 'react'
import {Label} from "@/components/ui/label";
import {Input} from "@/components/ui/input";
import {cn} from "@/lib/utils";

const InputField = ({name, label, placeholder, type ="text", register, error, validation, disabled, value, autoComplete}: FormInputProps) => {
    // Determinar el autocompletado si no se proporciona explícitamente
    const getAutoComplete = () => {
        if (autoComplete) return autoComplete;
        if (type === 'password') return 'current-password';
        if (type === 'email' || name.toLowerCase() === 'email') return 'username';
        if (name.toLowerCase().includes('name')) return 'name';
        return undefined;
    };

    // Teclado móvil con @ sin activar la validación nativa del navegador
    // (seguimos mostrando solo los mensajes ES de react-hook-form).
    const inputMode = (type === 'email' || name.toLowerCase() === 'email') ? 'email' as const : undefined;

    const errorId = `${name}-error`;

    return (
        <div className="space-y-2">
            <Label htmlFor={name} className="form-label">
                {label}
            </Label>
            <Input
                type={type}
                id={name}
                placeholder={placeholder}
                disabled={disabled}
                value={value}
                autoComplete={getAutoComplete()}
                inputMode={inputMode}
                aria-invalid={!!error}
                aria-describedby={error ? errorId : undefined}
                className={cn('form-input', {'opacity-50 cursor-not-allowed': disabled})}
                {...register(name, validation)}
            />
            {error && <p id={errorId} role="alert" className="text-sm text-red-500">{error.message}</p>}
        </div>
    )
}
export default InputField
