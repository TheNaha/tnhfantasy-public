import { Link, useLocation } from 'react-router-dom';
import { Home, Wand2, Settings, HardDrive, Menu, X, Settings2, BarChart3, Server } from 'lucide-react';
import { useMemo, useState } from 'react';
import clsx from 'clsx';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import KeyboardShortcutsModal from './KeyboardShortcutsModal';
import { useBrandingStore } from '../store/brandingStore';
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
                "flex items-center gap-3 px-4 py-3 rounded-lg transition-all focus-visible:ring-2 focus-visible:ring-blue-500 outline-none",
                isActive
                    ? "nav-active text-white font-medium"
                    : "text-gray-400 hover:bg-gray-800/50 hover:text-white"
            )}
        >
            <Icon size={20} className={isActive ? "text-blue-400" : ""} aria-hidden="true" />
            <span className="font-medium">{label}</span>
        </Link>
    );
};

const EMPTY_STATS = Object.freeze({});

export default function Layout({ children }) {
    const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
    const [showShortcutsModal, setShowShortcutsModal] = useState(false);
    const branding = useBrandingStore(state => state.branding);
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

    // Initialize global keyboard shortcuts
    useKeyboardShortcuts({
        onShowHelp: () => setShowShortcutsModal(true),
    });

    return (
        <div className="flex min-h-screen lg:h-screen bg-gray-900 text-white lg:overflow-hidden overflow-x-hidden">
            {/* Mobile Header */}
            <div className="lg:hidden fixed top-0 left-0 right-0 h-16 bg-gray-950/90 backdrop-blur-md border-b border-gray-800 flex items-center px-4 z-40">
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
                    <img src={branding.logoUrl} alt="Logo" className="w-6 h-6" />
                    <h1 className="text-lg font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">
                        {branding.appName}
                    </h1>
                </div>
            </div>

            {/* Mobile Overlay */}
            {isMobileMenuOpen && (
                <div
                    className="fixed inset-0 bg-black/50 z-40 lg:hidden"
                    onClick={() => setIsMobileMenuOpen(false)}
                />
            )}

            {/* Sidebar */}
            <div id="mobile-sidebar" className={clsx(
                "fixed inset-y-0 left-0 z-50 w-64 bg-gray-950 border-r border-gray-800 flex flex-col transition-transform duration-300 lg:static lg:translate-x-0",
                isMobileMenuOpen ? "translate-x-0" : "-translate-x-full"
            )}>
                <div className="p-6 flex items-center justify-between border-b border-gray-800 h-16 lg:h-auto">
                    <div className="flex items-center gap-2">
                        <img src={branding.logoUrl} alt="Logo" className="w-7 h-7" />
                        <h1 className="text-xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">
                            {branding.appName}
                        </h1>
                    </div>

                    {/* Close button only for mobile overlay mode */}
                    <button
                        onClick={() => setIsMobileMenuOpen(false)}
                        className="lg:hidden text-gray-400 hover:text-white focus-visible:ring-2 focus-visible:ring-blue-500 outline-none rounded-lg p-1"
                        aria-label="Close mobile menu"
                    >
                        <X size={24} aria-hidden="true" />
                    </button>
                </div>

                <nav className="flex-1 p-4 space-y-2 overflow-y-auto">
                    <NavItem to="/" icon={Home} label="Dashboard" />
                    <NavItem to="/generate" icon={Wand2} label="Simple Generate" />
                    <NavItem to="/advanced" icon={Settings} label="Advanced" />
                    <NavItem to="/models" icon={HardDrive} label="Models" />
                    <NavItem to="/providers" icon={Server} label="Providers" />
                    <NavItem to="/statistics" icon={BarChart3} label="Statistics" />
                    <NavItem to="/settings" icon={Settings2} label="Settings" />
                </nav>

                <div className="p-4 border-t border-gray-800">
                    <div className="bg-gray-900/60 rounded-xl p-3 border border-gray-800/60">
                        <div className="flex items-center justify-between mb-2.5">
                            <span className="text-[10px] font-semibold uppercase tracking-widest text-gray-500">System Status</span>
                            <span className={`inline-block h-2 w-2 rounded-full ${runningProviderCount > 0 ? 'bg-green-500' : 'bg-gray-600'}`} />
                        </div>
                        {providerEntries.length > 0 ? (
                            <div className="space-y-1.5">
                                {providerEntries.map(({ provider, summary }) => {
                                    const statusMeta = [
                                        summary.jobsAssigned > 0 ? `${summary.jobsAssigned} jobs` : null,
                                        summary.downloadsActive > 0 ? `${summary.downloadsActive} dl` : null,
                                        summary.downloadsQueued > 0 ? `${summary.downloadsQueued} queued` : null,
                                    ].filter(Boolean).join(' · ');

                                    const subtitle = [summary.message, statusMeta].filter(Boolean).join(' · ');

                                    return (
                                        <div key={provider.id} className="flex items-start gap-2 group">
                                            <span className={`provider-dot ${providerDotToneClass(summary.dotTone)}`} />
                                            <div className="min-w-0 flex-1">
                                                <div className="flex items-center gap-1.5">
                                                    <span className={`text-xs truncate ${providerTextToneClass(summary.stage)}`}>
                                                        {provider.id}
                                                    </span>
                                                    <span className={`inline-flex items-center rounded border px-1 py-0.5 text-[9px] font-medium uppercase tracking-wide ${providerBadgeToneClass(summary.stage)}`}>
                                                        {summary.label}
                                                    </span>
                                                    {summary.isDisabled && (
                                                        <span className="text-[9px] text-gray-600 ml-auto">off</span>
                                                    )}
                                                </div>
                                                {subtitle && (
                                                    <p className="mt-0.5 truncate text-[10px] text-gray-400" title={subtitle}>
                                                        {subtitle}
                                                    </p>
                                                )}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        ) : (
                            <p className="text-xs text-gray-600">No providers</p>
                        )}
                        <div className="mt-2.5 pt-2 border-t border-gray-800/50 text-xs text-gray-500">
                            {runningProviderCount}/{providers.length} online
                        </div>
                    </div>
                </div>
            </div>

            {/* Main Content */}
            <div className="flex-1 flex flex-col min-w-0 lg:overflow-hidden pt-16 lg:pt-0">
                <main id="main-scroll-container" className="flex-1 lg:overflow-y-auto px-2 py-3 sm:p-4 lg:p-8">
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
