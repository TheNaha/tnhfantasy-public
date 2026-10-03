import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
    ArrowRight,
    BookOpen,
    Compass,
    Globe2,
    MapPin,
    MessageSquare,
    PenLine,
    ScrollText,
    Sparkles,
    Users,
} from 'lucide-react';
import clsx from 'clsx';
import { useChats } from '../hooks/useChats';
import { useStories } from '../hooks/useStories';
import { useWorlds } from '../hooks/useWorlds';
import { useWorldVaultDashboard } from '../hooks/useWorldVaultSearch';
import OnboardingWizard from '../components/onboarding/OnboardingWizard';
import { QueryErrorState } from '../components/common/QueryState';
import { EXPERT_TOOLS } from '../constants/navigation';
import { isSetupComplete } from '../utils/setupComplete';

const asList = (value) => Array.isArray(value) ? value : (value?.chats || value?.stories || value?.worlds || []);

const formatUpdated = (value) => {
    if (!value) return 'Recently';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Recently';
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

export default function RoleplayWorkspace() {
    const navigate = useNavigate();
    const [showExpertTools, setShowExpertTools] = useState(false);
    // The first-run wizard is hosted here, not on /hub. This page is the only
    // front door (`/` redirects here) and /hub had no link pointing at it from
    // anywhere, so a new user was guaranteed to never see onboarding. The
    // wizard's own X and Skip both call markSetupComplete() before onClose(),
    // so dismissing it persists and it does not reappear on the next visit.
    const [showOnboarding, setShowOnboarding] = useState(() => !isSetupComplete());
    const chatsQuery = useChats({ limit: 8 });
    const storiesQuery = useStories();
    const worldsQuery = useWorlds();
    const vaultQuery = useWorldVaultDashboard();
    const { data: chatData, isLoading: chatsLoading } = chatsQuery;
    const { data: storyData, isLoading: storiesLoading } = storiesQuery;
    const { data: worldData } = worldsQuery;
    const { data: vault } = vaultQuery;

    // This is the app's only front door (`/` redirects here), and it had no
    // `isError` branch on any of its four queries. A failed fetch rendered
    // "Your next session will appear here — start with a chat or a story, no
    // setup required" and six count cards all reading `0`, next to a vault that
    // already held characters, chats and a story. It also popped the first-run
    // onboarding wizard at someone whose work already existed, because the
    // wizard is gated on localStorage rather than on the data having loaded.
    // See components/common/QueryState.jsx.
    const sessionsError = chatsQuery.isError || storiesQuery.isError;
    const worldError = vaultQuery.isError || worldsQuery.isError;
    const anyError = sessionsError || worldError;
    const retryAll = () => {
        if (sessionsError) { chatsQuery.refetch?.(); storiesQuery.refetch?.(); }
        if (worldError) { vaultQuery.refetch?.(); worldsQuery.refetch?.(); }
    };

    const chats = asList(chatData);
    const stories = asList(storyData);
    const worlds = asList(worldData);
    const isLoading = chatsLoading || storiesLoading;

    const sessions = useMemo(() => {
        return [
            ...chats.map((item) => ({ ...item, kind: 'chat', to: `/chat/${item.id}`, icon: MessageSquare, color: 'text-purple-300' })),
            ...stories.map((item) => ({ ...item, kind: 'story', to: `/story/${item.id}`, icon: BookOpen, color: 'text-amber-300' })),
        ]
            .sort((a, b) => new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0))
            .slice(0, 6);
    }, [chats, stories]);

    const counts = vault?.counts || {};

    return (
        <div className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8 space-y-8">
            <section className="relative overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-br from-purple-950/40 via-slate-950/60 to-cyan-950/30 p-6 sm:p-10">
                <div className="absolute -right-16 -top-24 h-64 w-64 rounded-full bg-cyan-500/10 blur-3xl" />
                <div className="relative max-w-3xl">
                    <div className="mb-4 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
                        <Compass size={15} aria-hidden="true" />
                        Roleplay workspace
                    </div>
                    <h1 className="text-3xl font-bold text-white sm:text-5xl">Your next scene starts here.</h1>
                    <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300 sm:text-base">
                        Start with a simple conversation or a story. Add more world detail only when you need it.
                    </p>
                    <div className="mt-7 flex flex-col gap-3 sm:flex-row">
                        <button
                            type="button"
                            onClick={() => navigate('/chat?new=1')}
                            className="inline-flex items-center justify-center gap-2 rounded-xl bg-cyan-500 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-cyan-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                        >
                            <PenLine size={17} aria-hidden="true" />
                            Start a chat
                        </button>
                        <button
                            type="button"
                            onClick={() => navigate('/story')}
                            className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/15 bg-white/5 px-5 py-3 text-sm font-semibold text-white transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                        >
                            <BookOpen size={17} aria-hidden="true" />
                            Write a story
                        </button>
                        <button
                            type="button"
                            onClick={() => navigate('/worlds')}
                            className="inline-flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium text-slate-300 transition hover:text-white"
                        >
                            Open your worlds <ArrowRight size={16} aria-hidden="true" />
                        </button>
                    </div>
                </div>
            </section>

            <section aria-labelledby="roleplay-start-heading">
                <div className="mb-4 flex items-end justify-between gap-4">
                    <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Beginner shortcuts</p>
                        <h2 id="roleplay-start-heading" className="mt-1 text-xl font-semibold text-white">Choose a way to play</h2>
                    </div>
                    <button
                        type="button"
                        onClick={() => navigate('/scenarios')}
                        className="hidden items-center gap-1 py-1 text-sm text-cyan-300 hover:text-cyan-200 sm:flex"
                    >
                        Browse scenarios <ArrowRight size={15} aria-hidden="true" />
                    </button>
                </div>
                <div className="grid gap-4 md:grid-cols-3">
                    <ShortcutCard
                        icon={MessageSquare}
                        title="Roleplay a character"
                        description="Chat with a character in a controlled scene."
                        actionLabel="New chat"
                        onClick={() => navigate('/chat?new=1')}
                        color="text-purple-300"
                    />
                    <ShortcutCard
                        icon={BookOpen}
                        title="Build a story"
                        description="Draft chapters, continue scenes, and add illustrations."
                        actionLabel="Open stories"
                        onClick={() => navigate('/story')}
                        color="text-amber-300"
                    />
                    <ShortcutCard
                        icon={Globe2}
                        title="Shape a world"
                        description="Group characters, locations, chats, and stories together."
                        actionLabel="Open worlds"
                        onClick={() => navigate('/worlds')}
                        color="text-cyan-300"
                    />
                </div>
            </section>

            <section aria-labelledby="roleplay-recent-heading">
                <div className="mb-4 flex items-center justify-between gap-4">
                    <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Pick up where you left off</p>
                        <h2 id="roleplay-recent-heading" className="mt-1 text-xl font-semibold text-white">Recent sessions</h2>
                    </div>
                    {sessions.length > 0 && (
                        <button type="button" onClick={() => navigate('/chat')} className="py-1 text-sm text-slate-400 hover:text-white">
                            View all <ArrowRight size={14} className="inline" aria-hidden="true" />
                        </button>
                    )}
                </div>
                {isLoading ? (
                    <div className="grid gap-3 md:grid-cols-2">
                        {[1, 2, 3, 4].map((item) => <div key={item} className="h-24 animate-pulse rounded-2xl border border-white/10 bg-white/5" />)}
                    </div>
                ) : sessionsError ? (
                    <QueryErrorState noun="sessions" onRetry={retryAll} className="border-slate-500/30 bg-slate-500/10" />
                ) : sessions.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-white/15 bg-white/5 p-6 text-center">
                        <Sparkles className="mx-auto text-cyan-300" size={24} />
                        <p className="mt-3 font-medium text-white">Your next session will appear here.</p>
                        <p className="mt-1 text-sm text-slate-400">Start with a chat or a story—no setup required.</p>
                    </div>
                ) : (
                    <div className="grid gap-3 md:grid-cols-2">
                        {sessions.map((session) => {
                            const Icon = session.icon;
                            return (
                                <button
                                    key={`${session.kind}-${session.id}`}
                                    type="button"
                                    onClick={() => navigate(session.to)}
                                    className="group flex items-center gap-4 rounded-2xl border border-white/10 bg-white/5 p-4 text-left transition hover:border-white/25 hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                                >
                                    <span className={clsx('flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/5', session.color)}>
                                        <Icon size={20} aria-hidden="true" />
                                    </span>
                                    <span className="min-w-0 flex-1">
                                        <span className="block truncate font-medium text-white">{session.name || session.title || 'Untitled session'}</span>
                                        <span className="mt-1 flex items-center gap-2 text-xs capitalize text-slate-500">
                                            <span>{session.kind}</span>
                                            <span>·</span>
                                            <span>{formatUpdated(session.updated_at || session.created_at)}</span>
                                        </span>
                                    </span>
                                    <ArrowRight size={16} className="text-slate-600 transition group-hover:translate-x-1 group-hover:text-cyan-300" aria-hidden="true" />
                                </button>
                            );
                        })}
                    </div>
                )}
            </section>

            <section aria-labelledby="roleplay-world-heading">
                <div className="mb-4 flex items-end justify-between gap-4">
                    <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Build as much world as you need</p>
                        <h2 id="roleplay-world-heading" className="mt-1 text-xl font-semibold text-white">Your world</h2>
                    </div>
                    <button type="button" onClick={() => navigate('/world-vault')} className="py-1 text-sm text-cyan-300 hover:text-cyan-200">
                        Search everything <ArrowRight size={14} className="inline" aria-hidden="true" />
                    </button>
                </div>
                {worldError ? (
                    <QueryErrorState
                        noun="world"
                        error={vaultQuery.error || worldsQuery.error}
                        onRetry={retryAll}
                        className="border-slate-500/30 bg-slate-500/10"
                    />
                ) : (
                    <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
                        <CountCard label="Characters" value={counts.characters || 0} icon={Users} onClick={() => navigate('/characters')} />
                        <CountCard label="Chats" value={counts.chats || 0} icon={MessageSquare} onClick={() => navigate('/chat')} />
                        <CountCard label="Stories" value={counts.stories || 0} icon={BookOpen} onClick={() => navigate('/story')} />
                        <CountCard label="Lorebooks" value={counts.lorebooks || 0} icon={ScrollText} onClick={() => navigate('/lorebooks')} />
                        <CountCard label="Locations" value={counts.locations || 0} icon={MapPin} onClick={() => navigate('/locations')} />
                        <CountCard label="Worlds" value={worlds.length} icon={Globe2} onClick={() => navigate('/worlds')} />
                    </div>
                )}
            </section>

            <section aria-labelledby="roleplay-expert-heading" className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 sm:p-5">
                <button
                    type="button"
                    onClick={() => setShowExpertTools((open) => !open)}
                    aria-expanded={showExpertTools}
                    className="flex w-full items-center justify-between text-left"
                >
                    <span>
                        <span className="block text-sm font-semibold text-white">Expert tools</span>
                        <span className="mt-1 block text-xs text-slate-500">Advanced entity management and world-building tools</span>
                    </span>
                    <span className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-400">{showExpertTools ? 'Hide' : 'Show'}</span>
                </button>
                {showExpertTools && (
                    <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                        {EXPERT_TOOLS.map(({ to, label, description, icon: Icon, color }) => (
                            <button
                                key={to}
                                type="button"
                                onClick={() => navigate(to)}
                                className="group flex items-center gap-3 rounded-xl border border-white/5 bg-white/5 p-3 text-left transition hover:border-white/20 hover:bg-white/10"
                            >
                                <Icon size={17} className={color} aria-hidden="true" />
                                <span className="min-w-0 flex-1">
                                    <span className="block text-sm font-medium text-white">{label}</span>
                                    <span className="block truncate text-xs text-slate-500">{description}</span>
                                </span>
                                <ArrowRight size={14} className="text-slate-600 group-hover:text-cyan-300" aria-hidden="true" />
                            </button>
                        ))}
                    </div>
                )}
            </section>
            {/* Gated on `!anyError` as well as on the flag: the wizard is the
                "you have nothing yet" flow, so showing it over a failed fetch
                tells a returning user their work does not exist. */}
            {showOnboarding && !anyError && <OnboardingWizard onClose={() => setShowOnboarding(false)} />}
        </div>
    );
}

function ShortcutCard({ icon: Icon, title, description, actionLabel, onClick, color }) {
    return (
        <button
            type="button"
            onClick={onClick}
            className="group flex flex-col items-start rounded-2xl border border-white/10 bg-white/5 p-5 text-left transition hover:-translate-y-0.5 hover:border-white/25 hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
        >
            <Icon size={23} className={color} aria-hidden="true" />
            <span className="mt-4 text-base font-semibold text-white">{title}</span>
            <span className="mt-1 min-h-10 text-sm leading-5 text-slate-400">{description}</span>
            <span className="mt-4 flex items-center gap-1 text-sm font-medium text-cyan-300">
                {actionLabel} <ArrowRight size={14} className="transition group-hover:translate-x-1" aria-hidden="true" />
            </span>
        </button>
    );
}

function CountCard({ label, value, icon: Icon, onClick }) {
    return (
        <button type="button" onClick={onClick} className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 p-3 text-left transition hover:border-white/25 hover:bg-white/10">
            <Icon size={17} className="text-cyan-300" aria-hidden="true" />
            <span>
                <span className="block text-lg font-semibold text-white">{value}</span>
                <span className="block text-xs text-slate-500">{label}</span>
            </span>
        </button>
    );
}
