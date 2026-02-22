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
        <div className="flex gap-6 border-b border-gray-800">
            {tabs.map((tab) => (
                <NavLink
                    key={tab.path}
                    to={tab.path}
                    className={`relative py-3 text-sm font-medium transition-colors ${
                        isActive(tab.path)
                            ? 'text-cyan-400'
                            : 'text-gray-400 hover:text-gray-200'
                    }`}
                >
                    {tab.label}
                    {/* Active indicator - blue underline */}
                    {isActive(tab.path) && (
                        <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-cyan-400" />
                    )}
                </NavLink>
            ))}
        </div>
    );
}
