import clsx from 'clsx';
import { Compass } from 'lucide-react';

export default function RoleplayPageShell({
    eyebrow = 'Roleplay',
    title,
    description,
    icon: Icon = Compass,
    actions,
    children,
    maxWidth = 'max-w-6xl',
    className,
}) {
    return (
        <div className={clsx('mx-auto w-full px-4 py-6 sm:px-6 lg:px-8', maxWidth, className)}>
            <header className="mb-6 flex flex-col gap-4 border-b border-white/10 pb-6 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 items-start gap-3">
                    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-cyan-400/20 bg-cyan-400/10 text-cyan-300">
                        <Icon size={21} aria-hidden="true" />
                    </span>
                    <div className="min-w-0">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-cyan-300">{eyebrow}</p>
                        <h1 className="mt-1 text-2xl font-bold tracking-tight text-white sm:text-3xl">{title}</h1>
                        {description && <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-400">{description}</p>}
                    </div>
                </div>
                {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
            </header>
            {children}
        </div>
    );
}
