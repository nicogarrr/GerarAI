'use client';

import React, { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react';
import {Label} from "@/components/ui/label";
import {Input} from "@/components/ui/input";
import {cn} from "@/lib/utils";
import {useT} from "@/lib/i18n/client";

const InputField = ({name, label, placeholder, type ="text", register, error, validation, disabled, value, autoComplete}: FormInputProps) => {
    const t = useT();
    const [showPassword, setShowPassword] = useState(false);
    const isPassword = type === 'password';
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
    const inputMode = name === 'totpCode' ? 'numeric' as const : (type === 'email' || name.toLowerCase() === 'email') ? 'email' as const : undefined;

    const errorId = `${name}-error`;

    return (
        <div className="space-y-2">
            <Label htmlFor={name} className="form-label">
                {label}
            </Label>
            <div className="relative">
            <Input
                type={isPassword && showPassword ? 'text' : type}
                id={name}
                placeholder={placeholder}
                disabled={disabled}
                value={value}
                autoComplete={getAutoComplete()}
                inputMode={inputMode}
                autoCapitalize={name.toLowerCase() === 'email' ? 'none' : undefined}
                spellCheck={name.toLowerCase() === 'email' || isPassword ? false : undefined}
                aria-invalid={!!error}
                aria-describedby={error ? errorId : undefined}
                className={cn('form-input', {'opacity-50 cursor-not-allowed': disabled, 'pr-14': isPassword})}
                {...register(name, validation)}
            />
            {isPassword && (
                <button
                    type="button"
                    aria-label={showPassword ? t('auth.fields.hidePassword') : t('auth.fields.showPassword')}
                    aria-pressed={showPassword}
                    aria-controls={name}
                    disabled={disabled}
                    onClick={() => setShowPassword((visible) => !visible)}
                    className="absolute inset-y-0 right-0 flex min-h-11 min-w-12 items-center justify-center rounded-r-lg text-gray-400 hover:text-teal-300 focus-visible:outline-2 focus-visible:outline-teal-400 disabled:opacity-50"
                >
                    {showPassword ? <EyeOff aria-hidden="true" className="h-5 w-5" /> : <Eye aria-hidden="true" className="h-5 w-5" />}
                </button>
            )}
            </div>
            {error && <p id={errorId} role="alert" className="text-sm text-red-500">{error.message}</p>}
        </div>
    )
}
export default InputField
