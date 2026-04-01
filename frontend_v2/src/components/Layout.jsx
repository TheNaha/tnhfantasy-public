import { Link, useLocation } from 'react-router-dom';
import { Home, Wand2, Settings, HardDrive, Menu, X, Settings2, BarChart3, Server } from 'lucide-react';
import { useState } from 'react';
import clsx from 'clsx';
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts';
import KeyboardShortcutsModal from './KeyboardShortcutsModal';
import { useBrandingStore } from '../store/brandingStore';
import { useProviderStore } from '../store/providerStore';

const NavItem = ({ to, icon: Icon, label }) => {
    const location = useLocation();
    const isActive = location.pathname === to;

    return (
        <Link
            to={to}
            className={clsx(
                "flex items-center gap-3 px-4 py-3 rounded-lg transition-all",
                isActive
                    ? "nav-active text-white font-medium"
                    : "text-gray-400 hover:bg-gray-800/50 hover:text-white"
            )}
        >
            <Icon size={20} className={isActive ? "text-blue-400" : ""} />
            <span className="font-medium">{label}</span>
        </Link>
    );
};

export default function Layout({ children }) {
    const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
    const [showShortcutsModal, setShowShortcutsModal] = useState(false);
    const branding = useBrandingStore(state => state.branding);
    const providers = useProviderStore(state => state.providers);
    const containerStatuses = useProviderStore(state => state.containerStatuses);
    const runningProviders = providers.filter(provider =>
        ['running', 'starting'].includes(containerStatuses[provider.id]?.status)
    );
    const statusLabel = runningProviders.length > 0
        ? `${runningProviders.length} provider${runningProviders.length === 1 ? '' : 's'} online`
        : 'No providers online';

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
                    className="p-2 text-gray-400 hover:text-white"
                >
                    <Menu size={24} />
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
            <div className={clsx(
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
                        className={clsx(
                            "lg:hidden text-gray-400 hover:text-white",
                            !isMobileMenuOpen && "hidden" // Ensure it's hidden when not in mobile menu mode if standard media queries fail
                        )}
                    >
                        <X size={24} />
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
                    <div className="bg-gray-900 rounded-lg p-3 text-sm text-gray-400">
                        <div className="flex justify-between items-center mb-2">
                            <span>Status</span>
                            <span className={`w-2 h-2 rounded-full ${runningProviders.length > 0 ? 'bg-green-500' : 'bg-gray-600'}`}></span>
                        </div>
                        <p>{statusLabel}</p>
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
