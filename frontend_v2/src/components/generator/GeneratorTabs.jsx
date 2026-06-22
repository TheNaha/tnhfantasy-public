import { NavLink, useLocation } from 'react-router-dom';

/**
 * Tab navigation for generator pages
 * Shows tabs with blue underline indicator for active tab
 */
export default function GeneratorTabs() {
    const location = useLocation();
    
    const tabs = [
        { label: 'Text2Img', path: '/generate' },
        { label: 'Img2Img', path: '/img2img' },
        { label: 'Edit', path: '/inpaint' },
    ];
    
    // Check if current path matches tab
    const isActive = (path) => {
        if (path === '/generate') {
            return location.pathname === '/generate' || location.pathname === '/generate/';
        }
        return location.pathname.startsWith(path);
    };

    return (
        <div className="flex gap-2 p-1.5 bg-black/40 border border-white/10 rounded-2xl w-fit shadow-inner mb-6">
            {tabs.map((tab) => (
                <NavLink
                    key={tab.path}
                    to={tab.path}
                    className={`relative px-6 py-2.5 text-sm font-bold rounded-xl transition-all duration-300 ${
                        isActive(tab.path)
                            ? 'text-white shadow-[0_0_15px_rgba(59,130,246,0.5)]'
                            : 'text-gray-400 hover:text-white hover:bg-white/5'
                    }`}
                >
                    <span className="relative z-10 tracking-wide">{tab.label}</span>
                    {/* Active indicator - glass background */}
                    {isActive(tab.path) && (
                        <div className="absolute inset-0 bg-gradient-to-r from-blue-600/80 to-violet-600/80 rounded-xl border border-white/20" />
                    )}
                </NavLink>
            ))}
        </div>
    );
}
