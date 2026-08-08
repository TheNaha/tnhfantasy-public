/**
 * BottomTabBar - shared, mobile-first tab navigation.
 *
 * Consolidates the per-page inline `flex lg:hidden` tab strips (ChatWorkspace
 * and StorySandbox) into one component — issue #1/#1.2. A single active layer
 * with safe-area padding; hidden on desktop where the sidebar nav applies.
 *
 * Modes:
 *   - default (fixed): `fixed bottom-0` overlay with an iOS safe-area spacer.
 *   - inline:           renders just the strip (caller controls placement).
 *
 * Props:
 *   tabs: Array<{ id, label, icon: IconComponent, badge?: number, color?: string }>
 *   value:    id of the currently active tab
 *   onChange: (id) => void
 *   inline:   render as an in-flow strip instead of a fixed bottom overlay
 *   label:    aria-label (default "Section navigation")
 */
import clsx from 'clsx';

function TabButton({ tab, value, onChange }) {
    const active = tab.id === value;
    const hasBadge = typeof tab.badge === 'number' && tab.badge > 0;
    return (
        <button
            type="button"
            onClick={() => onChange(tab.id)}
            aria-pressed={active}
            className={clsx(
                "flex flex-col items-center justify-center flex-1 h-full rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 transition-colors",
                active
                    ? (tab.color || "text-blue-400")
                    : "text-gray-500 hover:text-gray-300",
            )}
        >
            <span className="relative flex flex-col items-center gap-0.5">
                {tab.icon ? <tab.icon size={20} aria-hidden="true" /> : null}
                <span className="text-[10px] font-medium leading-tight">{tab.label}</span>
                {hasBadge && (
                    <span className="absolute -top-1 -right-2 flex items-center justify-center min-w-[16px] h-4 px-1 text-[8px] font-bold text-white bg-blue-500 rounded-full">
                        {tab.badge > 99 ? '99+' : tab.badge}
                    </span>
                )}
            </span>
        </button>
    );
}

export default function BottomTabBar({ tabs, value, onChange, label = 'Section navigation', inline }) {
    if (!tabs || tabs.length === 0) return null;

    const Tab = (tab) => <TabButton key={tab.id} tab={tab} value={value} onChange={onChange} />;

    if (inline) {
        // In-flow strip (e.g. ChatWorkspace bottom-of-flex): caller owns padding.
        return (
            <nav
                aria-label={label}
                className="lg:hidden shrink-0 flex items-center justify-around bg-gray-900 border-t border-white/5 p-2 pb-safe z-40"
            >
                {tabs.map(Tab)}
            </nav>
        );
    }

    return (
        <>
            {/* iOS / Android safe-area spacer */}
            <div className="lg:hidden fixed bottom-0 left-0 right-0 h-[env(safe-area-inset-bottom)] bg-[#0B0E14] z-30" />
            <nav
                aria-label={label}
                className="lg:hidden fixed bottom-0 left-0 right-0 z-40 pb-[env(safe-area-inset-bottom)] bg-gray-900/75 backdrop-blur-xl border-t border-white/5 shadow-[0_-2px_12px_rgba(0,0,0,0.5)]"
            >
                <div className="flex items-center justify-around h-14">
                    {tabs.map(Tab)}
                </div>
            </nav>
        </>
    );
}
