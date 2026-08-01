import { Link, useLocation } from 'react-router-dom';
import { Home, Wand2, Settings, HardDrive, Menu, X, Settings2, BarChart3, Server, Globe, MessageSquare, Users } from 'lucide-react';
import { useMemo, useState, memo } from 'react';
import clsx from 'clsx';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import KeyboardShortcutsModal from './KeyboardShortcutsModal';
import { useBranding } from '../hooks/useBranding';
import useProvidersPageData from '../hooks/useProvidersPageData';
import {
    providerBadgeToneClass,
    providerDotToneClass,
    providerTextToneClass,
    summarizeProviderStatus,
} from '../utils/providerStatus';

const NavItem = ({ to, icon: Icon, label }) => {
    const location = useLocation();
    const isActive = location.pathname === to;

    return (
        <Link
            to={to}
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
        <div className="p-4 border-t border-white/5">
            <div className="glass-panel rounded-xl p-4 border border-white/10">
                <div className="flex items-center justify-between mb-3">
                    <span className="text-[10px] font-semibold uppercase tracking-widest text-gray-400">System Status</span>
                    <span className={`inline-block h-2 w-2 rounded-full shadow-[0_0_8px_currentColor] ${runningProviderCount > 0 ? 'text-green-400 bg-green-400' : 'text-gray-500 bg-gray-500'}`} />
                </div>
                {providerEntries.length > 0 ? (
                    <div className="space-y-2">
                        {providerEntries.map(({ provider, summary }) => {
                            const statusMeta = [
                                summary.jobsAssigned > 0 ? `${summary.jobsAssigned} jobs` : null,
                                summary.downloadsActive > 0 ? `${summary.downloadsActive} dl` : null,
                                summary.downloadsQueued > 0 ? `${summary.downloadsQueued} queued` : null,
                            ].filter(Boolean).join(' · ');

                            const subtitle = [summary.message, statusMeta].filter(Boolean).join(' · ');

                            return (
                                <div key={provider.id} className="flex items-start gap-2.5 group">
                                    <span className={`mt-1 provider-dot shadow-[0_0_5px_currentColor] ${providerDotToneClass(summary.dotTone)}`} />
                                    <div className="min-w-0 flex-1">
                                        <div className="flex items-center gap-1.5">
                                            <span className={`text-xs truncate font-medium ${providerTextToneClass(summary.stage)}`}>
                                                {provider.id}
                                            </span>
                                            <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider bg-white/5 ${providerBadgeToneClass(summary.stage)}`}>
                                                {summary.label}
                                            </span>
                                            {summary.isDisabled && (
                                                <span className="text-[9px] text-gray-500 ml-auto font-medium">off</span>
                                            )}
                                        </div>
                                        {subtitle && (
                                            <p className="mt-1 truncate text-[10px] text-gray-500 group-hover:text-gray-400 transition-colors" title={subtitle}>
                                                {subtitle}
                                            </p>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                ) : (
                    <p className="text-xs text-gray-500">No providers connected</p>
                )}
                <div className="mt-3 pt-3 border-t border-white/5 text-[10px] font-medium text-gray-500 flex justify-between">
                    <span>Active Providers</span>
                    <span className="text-gray-300">{runningProviderCount}/{providers.length}</span>
                </div>
            </div>
        </div>
    );
});

export default function Layout({ children }) {
    const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
    const [showShortcutsModal, setShowShortcutsModal] = useState(false);
    const { data: branding } = useBranding();
    const safeBranding = branding || { appName: 'TNH-Comfy', logoUrl: '/logo.png', faviconUrl: '/favicon.ico' };

    // Initialize global keyboard shortcuts
    useKeyboardShortcuts({
        onShowHelp: () => setShowShortcutsModal(true),
    });

    return (
        <div className="flex min-h-screen lg:h-screen bg-[#0B0E14] text-gray-100 lg:overflow-hidden overflow-x-hidden font-sans selection:bg-blue-500/30 relative">
            {/* Global Ambient Background Gradients */}
            <div className="fixed top-[-20%] right-[-10%] w-[800px] h-[800px] bg-blue-600/10 rounded-full blur-[120px] pointer-events-none z-0" />
            <div className="fixed bottom-[-20%] left-[-10%] w-[800px] h-[800px] bg-purple-600/10 rounded-full blur-[120px] pointer-events-none z-0" />

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
                    <NavItem to="/" icon={Home} label="Dashboard" />
                    <NavItem to="/generate" icon={Wand2} label="Simple Generate" />
                    <NavItem to="/advanced" icon={Settings} label="Advanced" />
                    
                    <div className="mt-6 mb-3 px-4 text-[10px] font-semibold text-gray-500 uppercase tracking-widest">Roleplay</div>
                    <NavItem to="/chat" icon={MessageSquare} label="Chat Workspace" />
                    <NavItem to="/characters" icon={Users} label="Characters" />
                    
                    <div className="mt-6 mb-3 px-4 text-[10px] font-semibold text-gray-500 uppercase tracking-widest">Resources</div>
                    <NavItem to="/models/installed" icon={HardDrive} label="Installed Models" />
                    <NavItem to="/models/discover" icon={Globe} label="Discover Models" />
                    <NavItem to="/providers" icon={Server} label="Providers" />
                    <div className="mt-6 mb-3 px-4 text-[10px] font-semibold text-gray-500 uppercase tracking-widest">System</div>
                    <NavItem to="/statistics" icon={BarChart3} label="Statistics" />
                    <NavItem to="/settings" icon={Settings2} label="Settings" />
                </nav>

                <ProviderStatusPanel />
            </div>

            {/* Main Content */}
            <div className="flex-1 flex flex-col min-w-0 lg:overflow-hidden pt-16 lg:pt-0 relative z-10">
                
                <main id="main-scroll-container" className="flex-1 lg:overflow-y-auto px-2 py-3 sm:p-4 lg:p-8 relative z-10">
                    {children}
                </main>
            </div>



            {/* Keyboard Shortcuts Modal */}
            <KeyboardShortcutsModal
                isOpen={showShortcutsModal}
                onClose={() => setShowShortcutsModal(false)}
            />
        </div>
    );
}
