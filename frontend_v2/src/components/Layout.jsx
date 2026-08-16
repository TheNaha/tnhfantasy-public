import { Link, useLocation } from 'react-router-dom';
import { Home, Wand2, Settings, HardDrive, Menu, X, Settings2, BarChart3, Server, Globe, MessageSquare, Users, BookOpen, ImagePlus, Paintbrush, Images, MapPin, User, Sparkles, Calendar, Swords, GitBranch, HelpCircle, Command } from 'lucide-react';
import { useMemo, useState, memo, useEffect } from 'react';
import clsx from 'clsx';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import KeyboardShortcutsModal from './KeyboardShortcutsModal';
import GlobalCommandPalette from './GlobalCommandPalette';
import { useBranding } from '../hooks/useBranding';
import useProvidersPageData from '../hooks/useProvidersPageData';
import {
    providerBadgeToneClass,
    providerDotToneClass,
    providerTextToneClass,
    summarizeProviderStatus,
} from '../utils/providerStatus';

const NavItem = ({ to, icon: Icon, label, onNavigate }) => {
    const location = useLocation();
    const isActive = to === '/' ? location.pathname === '/' : location.pathname.startsWith(to);

    return (
        <Link
            to={to}
            onClick={onNavigate}
            aria-current={isActive ? 'page' : undefined}
            className={clsx(
                "group flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-300 focus-visible:ring-2 focus-visible:ring-blue-500 outline-none",
                isActive
                    ? "nav-active text-white font-medium shadow-[0_0_15px_rgba(59,130,246,0.15)]"
                    : "text-gray-400 hover:bg-white/5 hover:text-gray-200"
            )}
        >
            <Icon size={20} className={clsx(
                "transition-all duration-300",
                isActive ? "text-blue-400 drop-shadow-[0_0_8px_rgba(59,130,246,0.5)]" : "text-gray-500 group-hover:text-gray-300"
            )} aria-hidden="true" />
            <span className="font-medium tracking-wide text-sm">{label}</span>
        </Link>
    );
};

const EMPTY_STATS = Object.freeze({});

const ProviderStatusPanel = memo(function ProviderStatusPanel() {
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

    return (
        <div className="p-3 border-t border-white/5">
            <div className="glass-panel rounded-xl p-3 border border-white/10">
                <div className="flex items-center justify-between mb-2">
                    <span className="text-[9px] font-semibold uppercase tracking-widest text-gray-400">System Status</span>
                    <span className={`inline-block h-1.5 w-1.5 rounded-full shadow-[0_0_6px_currentColor] ${runningProviderCount > 0 ? 'text-green-400 bg-green-400' : 'text-gray-500 bg-gray-500'}`} />
                </div>
                {providerEntries.length > 0 ? (
                    <div className="space-y-1 max-h-52 overflow-y-auto custom-scrollbar pr-1">
                        {providerEntries.map(({ provider, summary }) => {
                            const statusMeta = [
                                summary.jobsAssigned > 0 ? `${summary.jobsAssigned} jobs` : null,
                                summary.downloadsActive > 0 ? `${summary.downloadsActive} dl` : null,
                                summary.downloadsQueued > 0 ? `${summary.downloadsQueued} queued` : null,
                            ].filter(Boolean).join(' · ');
                            const subtitle = [summary.message, statusMeta].filter(Boolean).join(' · ');

                            return (
                                <div
                                    key={provider.id}
                                    className="flex items-center gap-1.5 group"
                                    title={subtitle}
                                >
                                    <span className={`provider-dot shadow-[0_0_4px_currentColor] ${providerDotToneClass(summary.dotTone)}`} />
                                    <span className={`text-[10px] truncate font-medium ${providerTextToneClass(summary.stage)}`}>
                                        {provider.id}
                                    </span>
                                    <span className={`inline-flex items-center rounded border px-1 py-0.5 text-[8px] font-bold uppercase tracking-wider bg-white/5 ${providerBadgeToneClass(summary.stage)}`}>
                                        {summary.label}
                                    </span>
                                    {summary.isDisabled && (
                                        <span className="text-[8px] text-gray-500 ml-auto font-medium">off</span>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                ) : (
                    <p className="text-[11px] text-gray-500">No providers connected</p>
                )}
                <div className="mt-2 pt-2 border-t border-white/5 text-[9px] font-medium text-gray-500 flex justify-between">
                    <span>Active</span>
                    <span className="text-gray-300">{runningProviderCount}/{providers.length}</span>
                </div>
            </div>
        </div>
    );
});

export default function Layout({ children }) {
    const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
    const [showShortcutsModal, setShowShortcutsModal] = useState(false);
    const [showCommandPalette, setShowCommandPalette] = useState(false);
    const { data: branding } = useBranding();
    const safeBranding = branding || { appName: 'TNH-Comfy', logoUrl: '/logo.png', faviconUrl: '/favicon.ico' };
    const location = useLocation();
    const isFullBleed = /^\/(chat|story|characters)/.test(location.pathname);

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
                <div className="ml-4 flex items-center gap-2">
                    <img src={safeBranding.logoUrl} alt="Logo" className="w-6 h-6" />
                    <h1 className="text-lg font-bold text-gradient-primary">
                        {safeBranding.appName}
                    </h1>
                </div>
                <div className="ml-auto flex items-center gap-1">
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
                "fixed inset-y-0 left-0 z-50 w-64 bg-[#0B0E14]/95 backdrop-blur-xl border-r border-white/5 flex flex-col transition-transform duration-300 lg:static lg:translate-x-0 shadow-2xl shadow-black/50",
                isMobileMenuOpen ? "translate-x-0" : "-translate-x-full"
            )}>
                <div className="p-4 md:p-6 flex items-center justify-between border-b border-white/5 h-16 lg:h-auto">
                    <div className="flex items-center gap-3">
                        <img src={safeBranding.logoUrl} alt="Logo" className="w-8 h-8 drop-shadow-[0_0_10px_rgba(59,130,246,0.3)]" />
                        <h1 className="text-xl font-bold text-gradient-primary tracking-tight">
                            {safeBranding.appName}
                        </h1>
                    </div>

                    {/* Close button only for mobile overlay mode */}
                    <button
                        onClick={() => setIsMobileMenuOpen(false)}
                        className="lg:hidden text-gray-400 hover:text-white bg-white/5 rounded-full p-1.5"
                        aria-label="Close mobile menu"
                    >
                        <X size={20} aria-hidden="true" />
                    </button>
                </div>

                <nav className="flex-1 p-4 space-y-1 overflow-y-auto custom-scrollbar">
                    <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-widest mb-3 px-4">Menu</div>
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/" icon={Home} label="Home" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/gallery" icon={Images} label="Gallery" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/generate" icon={Wand2} label="Simple Generate" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/batch-generate" icon={Sparkles} label="Batch Generate" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/img2img" icon={ImagePlus} label="Img2Img" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/inpaint" icon={Paintbrush} label="Inpaint" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/advanced" icon={Settings} label="Advanced" />
                    
                    <div className="mt-6 mb-3 px-4 text-[10px] font-semibold text-gray-500 uppercase tracking-widest">Roleplay</div>
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/chat" icon={MessageSquare} label="Chat Workspace" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/story" icon={BookOpen} label="Story Sandbox" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/characters" icon={Users} label="Characters" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/avatar-gallery" icon={User} label="Avatar Gallery" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/world-timeline" icon={Calendar} label="World Timeline" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/campaigns" icon={Swords} label="Campaigns" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/world-graph" icon={GitBranch} label="World Graph" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/world-vault" icon={Globe} label="World Vault" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/locations" icon={MapPin} label="Locations" />
                    
                    <div className="mt-6 mb-3 px-4 text-[10px] font-semibold text-gray-500 uppercase tracking-widest">Resources</div>
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/models/installed" icon={HardDrive} label="Installed Models" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/models/discover" icon={Globe} label="Discover Models" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/providers" icon={Server} label="Providers" />
                    <div className="mt-6 mb-3 px-4 text-[10px] font-semibold text-gray-500 uppercase tracking-widest">System</div>
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/statistics" icon={BarChart3} label="Statistics" />
                    <NavItem onNavigate={() => setIsMobileMenuOpen(false)} to="/settings" icon={Settings2} label="Settings" />
                </nav>

                <ProviderStatusPanel />

                <div className="flex items-center gap-1 p-2 border-t border-white/5">
                    <button
                        onClick={() => setShowCommandPalette(true)}
                        className="flex items-center gap-2 px-3 py-2 rounded-xl text-gray-400 hover:text-gray-200 hover:bg-white/5 transition-colors text-xs font-medium"
                        aria-label="Open command palette"
                    >
                        <Command size={15} aria-hidden="true" />
                        <span>Quick search</span>
                        <kbd className="kbd ml-auto">⌘K</kbd>
                    </button>
                    <button
                        onClick={() => setShowShortcutsModal(true)}
                        className="p-2 rounded-xl text-gray-400 hover:text-gray-200 hover:bg-white/5 transition-colors"
                        aria-label="Keyboard shortcuts"
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
                    className={clsx(
                        "flex-1 relative z-10",
                        isFullBleed
                            ? "flex flex-col overflow-hidden"
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
