import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
    Home, Wand2, Settings, HardDrive, Menu, X, Settings2, BarChart3, Server,
    Globe, MessageSquare, BookOpen, Images, Sparkles, ChevronDown, Layers3,
    Command, HelpCircle, FileText, ImagePlus, Paintbrush, Image as ImageIcon,
    PanelLeftClose, PanelLeft, Cpu
} from 'lucide-react';
import { useMemo, useState, memo, useEffect, useRef } from 'react';
import clsx from 'clsx';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import KeyboardShortcutsModal from './KeyboardShortcutsModal';
import GlobalCommandPalette from './GlobalCommandPalette';
import { EXPERT_TOOLS } from '../constants/navigation';
import { useBranding } from '../hooks/useBranding';
import useProvidersPageData from '../hooks/useProvidersPageData';
import {
    providerBadgeToneClass,
    providerDotToneClass,
    providerTextToneClass,
    summarizeProviderStatus,
} from '../utils/providerStatus';

const NavItem = ({ to, icon: Icon, label, onNavigate, isCollapsed }) => {
    const location = useLocation();
    const isActive = to === '/' ? location.pathname === '/' : location.pathname.startsWith(to);

    return (
        <Link
            to={to}
            onClick={onNavigate}
            aria-label={label}
            title={label}
            aria-current={isActive ? 'page' : undefined}
            className={clsx(
                "group flex items-center rounded-xl transition-all duration-300 focus-visible:ring-2 focus-visible:ring-blue-500 outline-none",
                isCollapsed ? "lg:justify-center lg:px-0 lg:w-10 lg:h-10 mx-auto gap-3 px-4 py-2" : "gap-3 px-4 py-2",
                isActive
                    ? "nav-active text-white font-medium shadow-[0_0_15px_rgba(59,130,246,0.15)]"
                    : "text-gray-400 hover:bg-white/5 hover:text-gray-200"
            )}
        >
            <Icon size={20} className={clsx(
                "transition-all duration-300 shrink-0",
                isActive ? "text-blue-400 drop-shadow-[0_0_8px_rgba(59,130,246,0.5)]" : "text-gray-500 group-hover:text-gray-300"
            )} aria-hidden="true" />
            <span className={clsx("font-medium tracking-wide text-sm truncate", isCollapsed && "lg:hidden")}>{label}</span>
        </Link>
    );
};

const EMPTY_STATS = Object.freeze({});

const ProviderStatusPanel = memo(function ProviderStatusPanel({ isCollapsed }) {
    const { providers, lbStats } = useProvidersPageData();

    const providerStatsMap = useMemo(() => {
        const map = new Map();
        if (lbStats?.provider_stats) {
            lbStats.provider_stats.forEach((stat) => map.set(stat.id, stat));
        }
        return map;
    }, [lbStats]);

    const providerEntries = useMemo(() => providers.map((provider) => {
        const stats = providerStatsMap.get(provider.id) || EMPTY_STATS;
        const summary = summarizeProviderStatus(provider, {
            jobsAssigned: stats.jobs_assigned ?? 0,
            providerFailures: stats.failures ?? 0,
        });
        return { provider, stats, summary };
    }), [providerStatsMap, providers]);

    const runningProviderCount = providerEntries.filter((entry) => entry.summary.isOnline).length;
    const enabledProviderEntries = providerEntries.filter((entry) => !entry.summary.isDisabled);
    const disabledProviderCount = providerEntries.length - enabledProviderEntries.length;

    // Collapsed by default: this is diagnostics, not navigation, and at ~200px it
    // was permanently eating the nav column on a 900px-tall viewport.
    const [expanded, setExpanded] = useState(false);

    // Failures ONLY apply to enabled (active) providers. An intentionally paused provider is not a failure.
    const hasFailure = enabledProviderEntries.some(
        (entry) => entry.summary.errorCount > 0 || entry.summary.stage === 'error' || entry.summary.stage === 'deploy_failed'
    );
    const hasWarning = !hasFailure && enabledProviderEntries.some(
        (entry) => entry.summary.warningCount > 0 || entry.summary.stage === 'warning'
    );

    const statusDotTone = hasFailure
        ? 'text-red-400 bg-red-400'
        : hasWarning
            ? 'text-amber-400 bg-amber-400'
            : runningProviderCount > 0
                ? 'text-green-400 bg-green-400'
                : 'text-gray-500 bg-gray-500';

    const statusText = useMemo(() => {
        if (providerEntries.length === 0) return '0 providers';
        if (disabledProviderCount === 0) {
            return `${runningProviderCount}/${providerEntries.length} online`;
        }
        if (enabledProviderEntries.length === 0) {
            return `${disabledProviderCount} paused`;
        }
        return `${runningProviderCount}/${enabledProviderEntries.length} online · ${disabledProviderCount} paused`;
    }, [providerEntries.length, disabledProviderCount, enabledProviderEntries.length, runningProviderCount]);

    if (isCollapsed) {
        return (
            <div className="shrink-0 p-2 border-t border-white/5 hidden lg:flex justify-center">
                <Link
                    to="/providers"
                    className="relative p-2 rounded-xl text-gray-400 hover:text-gray-200 hover:bg-white/5 transition-colors"
                    title={`Providers: ${statusText}`}
                    aria-label={`Providers: ${statusText}`}
                >
                    <Server size={18} />
                    <span className={`absolute top-1 right-1 w-2 h-2 rounded-full ${statusDotTone}`} />
                </Link>
            </div>
        );
    }

    return (
        // `shrink-0` is load-bearing. Without it this panel is a flex child with
        // the default shrink:1, so in a constrained column it was compressed
        // below its own content height — and since nothing clips it, the content
        // painted straight over the navigation scrolling above it. Five nav items
        // were unreadable behind it.
        <div className="shrink-0 p-3 border-t border-white/5">
            <div className="glass-panel rounded-xl border border-white/10 overflow-hidden">
                <button
                    type="button"
                    onClick={() => setExpanded((open) => !open)}
                    aria-expanded={expanded}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-white/5 transition-colors"
                    title={
                        hasFailure
                            ? 'One or more active providers report errors or failures'
                            : disabledProviderCount > 0
                                ? `${runningProviderCount} of ${enabledProviderEntries.length} active providers online (${disabledProviderCount} paused intentionally)`
                                : `${runningProviderCount} of ${providerEntries.length} providers online`
                    }
                >
                    <span className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full shadow-[0_0_6px_currentColor] ${statusDotTone}`} />
                    <span className="text-xs font-medium text-gray-300 whitespace-nowrap">
                        {statusText}
                    </span>
                    {hasFailure && (
                        <span
                            className="text-2xs font-medium text-red-400 truncate"
                            title="Active provider is offline or reporting errors"
                        >
                            needs attention
                        </span>
                    )}
                    <ChevronDown
                        size={14}
                        aria-hidden="true"
                        className={`ml-auto text-gray-500 transition-transform ${expanded ? 'rotate-180' : ''}`}
                    />
                </button>
                {!expanded && (
                    <p className="px-3 pb-2 text-xs text-gray-500">
                        Details are on the{' '}
                        <Link to="/providers" className="text-blue-400 hover:text-blue-300 underline underline-offset-2">
                            Providers
                        </Link>{' '}
                        page.
                    </p>
                )}
                {expanded && (
                    <div className="px-3 pb-3 border-t border-white/5 pt-2">
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">System Status</span>
                        </div>
                {providerEntries.length > 0 ? (
                    <div className="space-y-1 max-h-52 overflow-y-auto custom-scrollbar pr-1">
                        {providerEntries.map(({ provider, summary }) => {
                            const statusMeta = [
                                summary.jobsAssigned > 0 ? `${summary.jobsAssigned} jobs` : null,
                                summary.downloadsActive > 0 ? `${summary.downloadsActive} dl` : null,
                                summary.downloadsQueued > 0 ? `${summary.downloadsQueued} queued` : null,
                            ].filter(Boolean).join(' · ');
                            const subtitle = summary.isDisabled
                                ? 'Intentionally paused — excluded from load balancer routing'
                                : [summary.message, statusMeta].filter(Boolean).join(' · ');

                            return (
                                <div
                                    key={provider.id}
                                    className="flex items-center gap-1.5 group"
                                    title={subtitle}
                                >
                                    <span className={`provider-dot shadow-[0_0_4px_currentColor] ${providerDotToneClass(summary.dotTone)}`} />
                                    <span className={`text-xs truncate font-medium ${providerTextToneClass(summary.stage)}`}>
                                        {provider.id}
                                    </span>
                                    <span className={`inline-flex items-center rounded border px-1 py-0.5 text-2xs font-semibold uppercase tracking-wide bg-white/5 ${providerBadgeToneClass(summary.stage)}`}>
                                        {summary.label}
                                    </span>
                                    {summary.isDisabled && (
                                        <span
                                            className="text-2xs text-gray-400 ml-auto font-medium"
                                            title="Paused by user — excluded from load balancer"
                                        >
                                            paused
                                        </span>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                ) : (
                    <p className="text-xs text-gray-500">No providers connected</p>
                )}
                        <div className="mt-2 pt-2 border-t border-white/5 text-xs font-medium text-gray-500 flex justify-between">
                            <span>Active Pool</span>
                            <span className="text-gray-300">
                                {runningProviderCount}/{enabledProviderEntries.length} online
                                {disabledProviderCount > 0 && (
                                    <span className="text-gray-500 ml-1">({disabledProviderCount} paused)</span>
                                )}
                            </span>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
});

export default function Layout({ children }) {
    const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(() => {
        try {
            return localStorage.getItem('tnh_sidebar_collapsed') === 'true';
        } catch {
            /* ignore storage quota/security error */
            return false;
        }
    });

    const toggleSidebarCollapse = () => {
        setIsSidebarCollapsed((prev) => {
            const next = !prev;
            try {
                localStorage.setItem('tnh_sidebar_collapsed', String(next));
            } catch {
                /* ignore storage quota/security error */
            }
            return next;
        });
    };

    const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
    const [showRoleplayTools, setShowRoleplayTools] = useState(false);
    const [showShortcutsModal, setShowShortcutsModal] = useState(false);
    const [showCommandPalette, setShowCommandPalette] = useState(false);
    const { data: branding } = useBranding();
    const safeBranding = branding || { appName: 'TNH-Comfy', logoUrl: '/logo.png', faviconUrl: '/favicon.ico' };
    const location = useLocation();
    const navigate = useNavigate();
    // Only on the gallery, which is where the floating button used to live. The
    // button itself is gone: see the header markup below.
    const showGeneratorShortcut = location.pathname === '/gallery' || location.pathname === '/';
    const isFullBleed = /^\/(chat|story|characters)/.test(location.pathname);
    const mainScrollRef = useRef(null);

    // Reset the scroll position on navigation.
    //
    // This <main> is rendered OUTSIDE `AnimatedRoutes`, so it is the same DOM
    // node for every page — and at `lg+` the window never scrolls, this pane
    // does. Nothing else reset it, so scrolling 2000px down the Gallery and
    // clicking "Settings" in the sidebar opened Settings 2000px down. Every
    // page pair inherited the previous page's offset.
    //
    // Deliberately not react-router's <ScrollRestoration/>: that is a data
    // router API and would also mean saving and restoring per-entry positions,
    // which is the opposite of what a settings page wants. Scrolling to the top
    // on a *pathname* change is the behaviour every other page-to-page
    // navigation in the app already has via the window.
    useEffect(() => {
        const el = mainScrollRef.current;
        if (el) el.scrollTop = 0;
        // Mobile: the pane is not the scroller below lg, the window is.
        window.scrollTo(0, 0);
    }, [location.pathname]);

    // Initialize global keyboard shortcuts
    useKeyboardShortcuts({
        onShowHelp: () => setShowShortcutsModal(true),
        onEscape: () => setShowShortcutsModal(false),
    });

    // Cmd/Ctrl+K opens the global command palette (ignored while typing in an input)
    useEffect(() => {
        const onKeyDown = (e) => {
            if (e.key.toLowerCase() !== 'k' || !(e.ctrlKey || e.metaKey)) return;
            const target = e.target;
            const typing =
                target instanceof HTMLElement &&
                (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);
            if (typing) return;
            e.preventDefault();
            setShowCommandPalette((open) => !open);
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, []);

    return (
        <div className="flex min-h-screen lg:h-screen bg-[#0B0E14] text-gray-100 lg:overflow-hidden overflow-x-hidden font-sans selection:bg-blue-500/30 relative">
            {/* Skip link. The sidebar is 17 nav items in a scrollable column
                that sits *before* <main> in the DOM, so on every one of the 25
                routes a keyboard or switch user had to tab through the whole
                navigation — and past the provider status panel and the ⌘K
                footer — to reach the page they navigated to. It is the first
                element in the tab order, invisible until focused, and the
                target is the scroll container every page already renders into
                (`mainScrollRef`), so the focus lands where the content is. */}
            <a
                href="#main-scroll-container"
                className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:inline-flex focus:items-center focus:rounded-lg focus:bg-blue-600 focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white focus:shadow-lg"
            >
                Skip to main content
            </a>

            {/* Global Ambient Background Gradients */}
            <div className="hidden md:block fixed top-[-20%] right-[-10%] w-[800px] h-[800px] bg-blue-600/10 rounded-full blur-[120px] pointer-events-none z-0" />
            <div className="hidden md:block fixed bottom-[-20%] left-[-10%] w-[800px] h-[800px] bg-purple-600/10 rounded-full blur-[120px] pointer-events-none z-0" />

            {/* Mobile Header */}
            <div className="lg:hidden fixed top-0 left-0 right-0 h-16 glass-panel border-b border-white/5 flex items-center px-4 z-40">
                <button
                    onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
                    className="p-2 text-gray-400 hover:text-white focus-visible:ring-2 focus-visible:ring-blue-500 outline-none rounded-lg"
                    aria-label="Toggle mobile menu"
                    aria-expanded={isMobileMenuOpen}
                    aria-controls="mobile-sidebar"
                >
                    <Menu size={24} aria-hidden="true" />
                </button>
                {/* `min-w-0` + `truncate` on the title block. Three icon buttons
                    plus a long app name no longer fit a 360px header, and without
                    a zero minimum the `<h1>` wrapped to two lines — "TNH-" /
                    "Comfy" — which made the header twice as tall and visibly
                    broken. The name is branding, not content, so it gives way
                    before the controls do. */}
                <div className="ml-4 flex items-center gap-2 min-w-0 flex-1">
                    <img src={safeBranding.logoUrl} alt="Logo" className="w-6 h-6 shrink-0" />
                    <h1 className="text-lg font-bold text-gradient-primary truncate">
                        {safeBranding.appName}
                    </h1>
                </div>
                <div className="ml-auto flex items-center gap-1">
                    {/* The generator shortcut lives here rather than floating over
                        the gallery. As a `fixed` circle at `bottom-6 right-6` it
                        sat on top of scrolling content, and measured across a full
                        scroll of /gallery at 360px it covered "Add to favorites"
                        **100%** — the control was completely unreachable — plus 18%
                        of "Sort images", 15% of the date rail and 13% of the LoRA
                        filter. A FAB over a scrolling page is always over
                        something; the header is not. Shown on mobile only, because
                        the sidebar already carries it on desktop. */}
                    {showGeneratorShortcut && (
                        <button
                            onClick={() => navigate('/generate')}
                            className="lg:hidden p-2 text-gray-400 hover:text-white focus-visible:ring-2 focus-visible:ring-blue-500 outline-none rounded-lg"
                            aria-label="Go to Generator"
                            title="Go to Generator"
                        >
                            <ImageIcon size={20} aria-hidden="true" />
                        </button>
                    )}
                    <button
                        onClick={() => setShowCommandPalette(true)}
                        className="p-2 text-gray-400 hover:text-white focus-visible:ring-2 focus-visible:ring-blue-500 outline-none rounded-lg"
                        aria-label="Open command palette"
                        title="Command palette (Cmd/Ctrl+K)"
                    >
                        <Command size={20} aria-hidden="true" />
                    </button>
                    <button
                        onClick={() => setShowShortcutsModal(true)}
                        className="p-2 text-gray-400 hover:text-white focus-visible:ring-2 focus-visible:ring-blue-500 outline-none rounded-lg"
                        aria-label="Keyboard shortcuts"
                        title="Keyboard shortcuts (?)"
                    >
                        <HelpCircle size={20} aria-hidden="true" />
                    </button>
                </div>
            </div>

            {/* Mobile Overlay */}
            {isMobileMenuOpen && (
                <div
                    className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 lg:hidden"
                    onClick={() => setIsMobileMenuOpen(false)}
                />
            )}

            {/* Sidebar */}
            <div id="mobile-sidebar" className={clsx(
                "fixed inset-y-0 left-0 z-50 bg-[#0B0E14]/95 backdrop-blur-xl border-r border-white/5 flex flex-col transition-all duration-300 lg:static lg:translate-x-0 shadow-2xl shadow-black/50",
                isMobileMenuOpen ? "translate-x-0" : "-translate-x-full",
                isSidebarCollapsed ? "w-64 lg:w-16" : "w-64"
            )}>
                <div className={clsx(
                    "p-4 flex items-center border-b border-white/5 h-16 transition-all",
                    isSidebarCollapsed ? "lg:p-2 lg:justify-center justify-between" : "md:p-6 justify-between"
                )}>
                    <div className="flex items-center gap-3 min-w-0">
                        <img src={safeBranding.logoUrl} alt="Logo" className="w-8 h-8 shrink-0 drop-shadow-[0_0_10px_rgba(59,130,246,0.3)]" />
                        <h1 className={clsx("text-xl font-bold text-gradient-primary tracking-tight truncate", isSidebarCollapsed && "lg:hidden")}>
                            {safeBranding.appName}
                        </h1>
                    </div>

                    {/* Collapse toggle button on desktop (shown when expanded) */}
                    <button
                        type="button"
                        onClick={toggleSidebarCollapse}
                        className={clsx(
                            "hidden lg:flex items-center justify-center p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-colors",
                            isSidebarCollapsed && "hidden"
                        )}
                        aria-label="Collapse sidebar"
                        title="Collapse sidebar"
                    >
                        <PanelLeftClose size={18} />
                    </button>

                    {/* Close button only for mobile overlay mode */}
                    <button
                        onClick={() => setIsMobileMenuOpen(false)}
                        className="lg:hidden text-gray-400 hover:text-white bg-white/5 rounded-full p-1.5"
                        aria-label="Close mobile menu"
                    >
                        <X size={20} aria-hidden="true" />
                    </button>
                </div>

                {/* When collapsed on desktop, show expand button */}
                {isSidebarCollapsed && (
                    <div className="hidden lg:flex justify-center py-2 border-b border-white/5">
                        <button
                            type="button"
                            onClick={toggleSidebarCollapse}
                            className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
                            aria-label="Expand sidebar"
                            title="Expand sidebar"
                        >
                            <PanelLeft size={18} />
                        </button>
                    </div>
                )}

                {/* `flex-1 min-h-0` is what makes this actually scroll: without
                    `min-h-0` a flex child refuses to shrink below its content, so
                    the column overflowed the viewport instead of scrolling.
                    The mask fades the final row so a scrollable nav reads as
                    scrollable — at 900px tall there are more items below. */}
                <nav
                    className={clsx(
                        "flex-1 min-h-0 pt-4 pb-1 space-y-1 overflow-y-auto custom-scrollbar transition-all",
                        isSidebarCollapsed ? "lg:px-2 px-4" : "px-4"
                    )}
                    // A 16px fade left the last item looking greyed-out — people read
                    // it as "disabled" rather than "scroll". 40px plus a short hold
                    // reads unmistakably as content continuing past the edge.
                    style={{
                        maskImage: 'linear-gradient(to bottom, black calc(100% - 44px), transparent 100%)',
                        WebkitMaskImage: 'linear-gradient(to bottom, black calc(100% - 44px), transparent 100%)',
                    }}
                >
                    <div className={clsx("text-2xs font-semibold text-gray-500 uppercase tracking-wider mb-2 px-4", isSidebarCollapsed && "lg:hidden")}>Roleplay</div>
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/roleplay" icon={Home} label="Home" isCollapsed={isSidebarCollapsed} />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/chat" icon={MessageSquare} label="Play" isCollapsed={isSidebarCollapsed} />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/story" icon={BookOpen} label="Stories" isCollapsed={isSidebarCollapsed} />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/worlds" icon={Globe} label="World" isCollapsed={isSidebarCollapsed} />
                    {!isSidebarCollapsed ? (
                        <>
                            <button
                                type="button"
                                onClick={() => setShowRoleplayTools((open) => !open)}
                                aria-expanded={showRoleplayTools}
                                className="mt-2 flex w-[calc(100%_-_2rem)] items-center gap-3 rounded-xl px-4 py-2.5 text-left text-xs font-medium text-gray-500 transition hover:bg-white/5 hover:text-gray-200"
                            >
                                <Layers3 size={17} aria-hidden="true" />
                                <span className="flex-1">Expert tools</span>
                                <ChevronDown size={14} className={showRoleplayTools ? 'rotate-180 transition-transform' : 'transition-transform'} aria-hidden="true" />
                            </button>
                            {showRoleplayTools && (
                                <div className="mt-1 space-y-1 border-l border-white/10 pl-3 ml-4">
                                    {EXPERT_TOOLS.map(({ to, icon: Icon, label }) => (
                                        <NavItem key={to} onNavigate={() => setIsMobileMenuOpen(false)} to={to} icon={Icon} label={label} isCollapsed={isSidebarCollapsed} />
                                    ))}
                                </div>
                            )}
                        </>
                    ) : (
                        <div className="hidden lg:block my-2 border-t border-white/5" />
                    )}

                    <div className={clsx("mt-4 mb-1.5 px-4 text-2xs font-semibold text-gray-500 uppercase tracking-wider", isSidebarCollapsed && "lg:hidden")}>Image generation</div>
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/gallery" icon={Images} label="Gallery" isCollapsed={isSidebarCollapsed} />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/generate" icon={Wand2} label="Simple Generate" isCollapsed={isSidebarCollapsed} />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/batch-generate" icon={Sparkles} label="Batch Generate" isCollapsed={isSidebarCollapsed} />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/prompts" icon={FileText} label="Prompt Library" isCollapsed={isSidebarCollapsed} />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/img2img" icon={ImagePlus} label="Img2Img" isCollapsed={isSidebarCollapsed} />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/inpaint" icon={Paintbrush} label="Inpaint" isCollapsed={isSidebarCollapsed} />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/advanced" icon={Settings} label="Advanced" isCollapsed={isSidebarCollapsed} />

                    <div className={clsx("mt-4 mb-1.5 px-4 text-2xs font-semibold text-gray-500 uppercase tracking-wider", isSidebarCollapsed && "lg:hidden")}>Resources</div>
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/models/installed" icon={HardDrive} label="Installed Models" isCollapsed={isSidebarCollapsed} />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/models/discover" icon={Globe} label="Discover Models" isCollapsed={isSidebarCollapsed} />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/providers" icon={Server} label="Providers" isCollapsed={isSidebarCollapsed} />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/llm-studio" icon={Cpu} label="LLM Studio" isCollapsed={isSidebarCollapsed} />
                    <div className={clsx("mt-4 mb-1.5 px-4 text-2xs font-semibold text-gray-500 uppercase tracking-wider", isSidebarCollapsed && "lg:hidden")}>System</div>
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/statistics" icon={BarChart3} label="Statistics" isCollapsed={isSidebarCollapsed} />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/settings" icon={Settings2} label="Settings" isCollapsed={isSidebarCollapsed} />
                </nav>

                <ProviderStatusPanel isCollapsed={isSidebarCollapsed} />

                <div className={clsx("flex items-center p-2 border-t border-white/5", isSidebarCollapsed ? "lg:flex-col lg:gap-2 justify-center" : "gap-1")}>
                    <button
                        onClick={() => setShowCommandPalette(true)}
                        className={clsx(
                            "flex items-center rounded-xl text-gray-400 hover:text-gray-200 hover:bg-white/5 transition-colors text-xs font-medium",
                            isSidebarCollapsed ? "lg:justify-center lg:p-2 lg:w-10 lg:h-10 gap-2 px-3 py-2 w-full" : "gap-2 px-3 py-2 w-full"
                        )}
                        aria-label="Open command palette"
                        title="Quick search (Cmd/Ctrl+K)"
                    >
                        <Command size={15} aria-hidden="true" />
                        <span className={clsx(isSidebarCollapsed && "lg:hidden")}>Quick search</span>
                        <kbd className={clsx("kbd ml-auto", isSidebarCollapsed && "lg:hidden")}>⌘K</kbd>
                    </button>
                    <button
                        onClick={() => setShowShortcutsModal(true)}
                        className="p-2 rounded-xl text-gray-400 hover:text-gray-200 hover:bg-white/5 transition-colors"
                        aria-label="Keyboard shortcuts"
                        title="Keyboard shortcuts (?)"
                    >
                        <HelpCircle size={16} aria-hidden="true" />
                    </button>
                </div>
            </div>

            {/* Main Content */}
            <div className={clsx(
                "flex-1 flex flex-col min-w-0 pt-16 lg:pt-0 relative z-10",
                // Full-bleed routes (/chat, /story) get a fixed viewport height on mobile too,
                // so their internal flex layout (sticky bottom tab bar, internal scroll areas) works.
                isFullBleed ? "h-[calc(var(--vh,1vh)*100)] overflow-hidden" : "lg:overflow-hidden"
            )}>
                {/* Full-bleed routes (/chat, /story) get no padding so they fill edge-to-edge */}
                <main
                    id="main-scroll-container"
                    ref={mainScrollRef}
                    // `tabIndex={-1}` is what makes the skip link work. A
                    // fragment link scrolls to the target but leaves focus on
                    // the link itself unless the target can take focus, so the
                    // next Tab would carry on from the top of the nav. -1 puts
                    // <main> in the tab order without adding a stop for
                    // everyone else.
                    tabIndex={-1}
                    className={clsx(
                        "flex-1 relative z-10",
                        isFullBleed
                            // `overflow-x-auto` is not optional here. This was
                            // `overflow-hidden` on both axes, so the story beats
                            // toolbar — which is a `flex gap-2 shrink-0` row of
                            // Narrate / Export / Publish / Add — was clipped at
                            // the viewport edge with no way to reach it. Measured
                            // at 768x1024: 220px clipped, 6 controls entirely
                            // outside the viewport, "Narrate" cut mid-word.
                            // Vertical scroll stays exactly as it was.
                            ? "flex flex-col overflow-y-auto overflow-x-auto"
                            : "lg:overflow-y-auto px-2 py-3 sm:p-4 lg:p-8"
                    )}
                >
                    {children}
                </main>
            </div>



            {/* Keyboard Shortcuts Modal */}
            <KeyboardShortcutsModal
                isOpen={showShortcutsModal}
                onClose={() => setShowShortcutsModal(false)}
            />

            {/* Global Command Palette (Cmd/Ctrl+K) — conditionally mounted so state resets per open */}
            {showCommandPalette && (
                <GlobalCommandPalette
                    onClose={() => setShowCommandPalette(false)}
                />
            )}
        </div>
    );
}
