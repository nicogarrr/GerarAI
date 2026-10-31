import type { PublicProfile } from '@/lib/actions/investors.actions';

const LINK = 'text-gray-300 underline-offset-2 hover:underline';

/** Ficha pública sin 13F: vehículo, cifras con fuente y fecha, cartas y reuniones. "Sin datos" solo por bloque. */
export function PublicProfileSection({ profile }: { profile: PublicProfile }) {
    const { vehicle } = profile;
    return (
        <div className="flex flex-col gap-10">
            <section className="flex flex-col gap-2 rounded-2xl border border-gray-800 bg-surface-1 p-6">
                <h2 className="text-xl font-semibold text-gray-100">{vehicle.name}</h2>
                <p className="text-sm text-gray-400">{vehicle.type}</p>
                <p className="text-sm text-gray-500">
                    {vehicle.regulator_id}
                    {vehicle.start_date ? ` · Inicio ${vehicle.start_date}` : ''}
                </p>
            </section>

            <section className="flex flex-col gap-3">
                <h2 className="text-xl font-semibold text-gray-100">Cifras publicadas</h2>
                <ul className="flex flex-col divide-y divide-gray-900">
                    {profile.facts.map((fact) => (
                        <li className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-3" key={fact.label}>
                            <span className="text-sm text-gray-300">{fact.label}</span>
                            <span className="text-sm font-medium text-gray-100">{fact.value}</span>
                            <span className="w-full text-xs text-gray-500">
                                {fact.kind === 'oficial' ? 'Oficial' : fact.kind === 'prensa' ? 'Prensa' : 'Inferido'} · {fact.as_of}
                            </span>
                        </li>
                    ))}
                </ul>
            </section>

            <section className="flex flex-col gap-3">
                <h2 className="text-xl font-semibold text-gray-100">Cartera</h2>
                <p className="text-sm text-gray-500">{profile.holdings_note}</p>
            </section>

            {profile.letters.length > 0 ? (
                <section className="flex flex-col gap-3">
                    <h2 className="text-xl font-semibold text-gray-100">Fuentes sobre el inversor</h2>
                    <ul className="flex flex-col divide-y divide-gray-900">
                        {profile.letters.map((letter) => (
                            <li className="py-2 text-sm" key={letter.url}>
                                <a className={LINK} href={letter.url} rel="noreferrer" target="_blank">
                                    {letter.title}
                                </a>
                            </li>
                        ))}
                    </ul>
                </section>
            ) : null}

            {profile.meetings.length > 0 ? (
                <section className="flex flex-col gap-3">
                    <h2 className="text-xl font-semibold text-gray-100">Reuniones anuales</h2>
                    <ul className="flex flex-col divide-y divide-gray-900">
                        {profile.meetings.map((meeting) => (
                            <li className="py-2 text-sm" key={meeting.url}>
                                <a className={LINK} href={meeting.url} rel="noreferrer" target="_blank">
                                    {meeting.title}
                                </a>
                            </li>
                        ))}
                    </ul>
                </section>
            ) : null}

            <p className="text-xs text-gray-500">
                Fuentes:{' '}
                {profile.links.map((link, index) => (
                    <span key={link.url}>
                        {index > 0 ? ' · ' : ''}
                        <a className={LINK} href={link.url} rel="noreferrer" target="_blank">
                            {link.label}
                        </a>
                    </span>
                ))}
                . {profile.provenance_note}
            </p>
        </div>
    );
}
