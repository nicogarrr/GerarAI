'use client';

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { BrainCircuit, ChevronDown, CircleHelp, LogOut, Settings, ShieldCheck } from "lucide-react";
import { signOut } from "@/lib/actions/auth.actions";
import { toast } from "sonner";
import { runSignOut } from "@/lib/auth/sign-out-flow";
import { useT } from "@/lib/i18n/client";

const UserDropdown = ({ user }: { user: User }) => {
    const router = useRouter();
    const t = useT();
    const handleSignOut = async () => {
        await runSignOut({
            signOut,
            push: (path) => router.push(path),
            refresh: () => router.refresh(),
            notifyError: (title, description) => toast.error(title, { description }),
        });
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                {/* Sin aria-label: el nombre accesible sale del texto (WCAG 2.5.3,
                    label-in-name). El nombre visible va aria-hidden y la etiqueta
                    completa se interpola en UN solo span sr-only: con dos spans
                    hermanos Chromium metia un espacio al calcular el nombre y
                    quedaba "…borrable , menú de usuario" (espacio antes de la
                    coma). En móvil el nombre se oculta a la vista pero no al
                    lector… salvo que ahora el lector usa el span interpolado. */}
                <Button className="flex items-center gap-2 bg-gray-800 hover:bg-gray-700">
                    <Avatar aria-hidden="true" className="h-8 w-8">
                        <AvatarFallback className="bg-teal-500 text-gray-900 text-sm font-bold">
                            {user.name[0]}
                        </AvatarFallback>
                    </Avatar>
                    <span aria-hidden="true" className="sr-only text-sm font-medium text-gray-400 md:not-sr-only md:inline">{user.name}</span>
                    <span className="sr-only">{t('shell.user.menuLabel', { name: user.name })}</span>
                    <ChevronDown aria-hidden="true" className="hidden h-4 w-4 text-gray-500 md:inline" />
                </Button>
            </DropdownMenuTrigger>
            {/* `align="end" + sideOffset` sustituye al `relative right-5` con el
                que se corrigia a mano la alineacion del menu. El tope de ancho
                evita que un nombre o email largo desborde la pantalla en
                movil (390px): el texto se trunca, el menu no empuja el layout. */}
            <DropdownMenuContent align="end" sideOffset={8} className="max-w-[calc(100vw-1rem)] bg-gray-800 text-gray-400">
                <DropdownMenuLabel>
                    <div className="flex items-center gap-3 py-2">
                        <Avatar className="h-10 w-10 shrink-0">
                            <AvatarFallback className="bg-teal-500 text-gray-900 text-sm font-bold">
                                {user.name[0]}
                            </AvatarFallback>
                        </Avatar>
                        <div className="flex min-w-0 flex-col">
                            <span className='truncate text-base font-medium text-gray-400'>
                                {user.name}
                            </span>
                            <span className="truncate text-sm text-gray-500">{user.email}</span>
                        </div>
                    </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator className="bg-gray-600" />
                <DropdownMenuItem
                    onClick={() => router.push("/help")}
                    className="cursor-pointer text-sm font-medium text-gray-100 transition-colors focus:text-teal-300"
                >
                    <CircleHelp aria-hidden="true" className="mr-2 hidden h-4 w-4 sm:block" />
                    Ayuda
                </DropdownMenuItem>
                <DropdownMenuSeparator className="bg-gray-600" />
                <DropdownMenuItem
                    onClick={() => router.push("/settings#llm")}
                    className="cursor-pointer text-sm font-medium text-gray-100 transition-colors focus:text-teal-300"
                >
                    <BrainCircuit aria-hidden="true" className="mr-2 hidden h-4 w-4 sm:block" />
                    {t('shell.user.aiModel')}
                </DropdownMenuItem>
                <DropdownMenuItem
                    onClick={() => router.push("/settings")}
                    className="cursor-pointer text-sm font-medium text-gray-100 transition-colors focus:text-teal-300"
                >
                    <Settings aria-hidden="true" className="mr-2 hidden h-4 w-4 sm:block" />
                    {t('shell.user.settings')}
                </DropdownMenuItem>
                <DropdownMenuItem
                    onClick={() => router.push("/security")}
                    className="cursor-pointer text-sm font-medium text-gray-100 transition-colors focus:text-teal-300"
                >
                    <ShieldCheck aria-hidden="true" className="mr-2 hidden h-4 w-4 sm:block" />
                    {t('shell.user.security')}
                </DropdownMenuItem>
                <DropdownMenuItem
                    onClick={handleSignOut}
                    className="cursor-pointer text-sm font-medium text-gray-100 transition-colors focus:text-teal-300"
                >
                    <LogOut aria-hidden="true" className="mr-2 hidden h-4 w-4 sm:block" />
                    {t('shell.user.signOut')}
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
export default UserDropdown
