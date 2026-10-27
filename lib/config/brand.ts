// Correo de contacto del producto: el mismo que ya usan las notificaciones de
// "Pedir acceso" y el User-Agent de SEC. Se puede sobreescribir por despliegue
// con NEXT_PUBLIC_SUPPORT_EMAIL.
export const SUPPORT_EMAIL = process.env.NEXT_PUBLIC_SUPPORT_EMAIL?.trim() || 'nicoiglesiasgarcia10@gmail.com';
