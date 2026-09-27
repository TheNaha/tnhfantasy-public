import { Star, FolderOpen, Layers, BarChart3, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export function DashboardToolbar({
    showFavorites,
    setShowFavorites,
    favoritesCount,
    activeCollection,
    activeCollectionName,
    setShowCollectionsPanel,
    onClearHistory,
    isSessionView,
    onOpenSessionPanel,
    onToggleViewMode
}) {
    const navigate = useNavigate();
    return (
        <div className="flex items-center gap-2 flex-wrap">
            <button
                onClick={() => setShowFavorites(!showFavorites)}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors text-sm ${showFavorites ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30' : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-yellow-400 border border-gray-700'}`}
                title={showFavorites ? 'Show All Images' : 'Show Favorites Only'}
                type="button"
            >
                <Star size={16} className={showFavorites ? 'fill-current' : ''} aria-hidden="true" />
                <span>Favorites</span>
                {favoritesCount > 0 && (
                    <span className="px-1.5 py-0.5 bg-yellow-500/30 rounded text-xs font-medium">{favoritesCount}</span>
                )}
            </button>

            <button
                onClick={() => setShowCollectionsPanel(true)}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors text-sm ${activeCollection ? 'bg-purple-500/20 text-purple-400 border border-purple-500/30' : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-purple-400 border border-gray-700'}`}
                title={activeCollectionName ? `Viewing collection: ${activeCollectionName}` : 'Browse collections'}
                type="button"
            >
                <FolderOpen size={16} aria-hidden="true" />
                <span className="hidden sm:inline">
                    {activeCollectionName ? activeCollectionName : 'Collections'}
                </span>
                <span className="sm:hidden">Collections</span>
            </button>

            {/* The session controls live here, beside Favorites and Collections,
                rather than on a row of their own. Two rows of pill buttons for
                one feature is vertical space taken from the images, and these
                three are three facets of the same question: what am I looking
                at, and how do I narrow it. */}
            <button
                onClick={onOpenSessionPanel}
                className="flex items-center gap-2 px-3 py-2 rounded-lg transition-colors text-sm bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-purple-400 border border-gray-700"
                title="Detect, curate, merge and split sessions"
                type="button"
            >
                <Layers size={16} aria-hidden="true" />
                <span className="hidden sm:inline">Manage sessions</span>
                <span className="sm:hidden">Sessions</span>
            </button>

            <button
                onClick={onToggleViewMode}
                aria-pressed={isSessionView}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg transition-colors text-sm border ${
                    isSessionView
                        ? 'bg-purple-600 text-white border-purple-500'
                        : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-purple-400 border-gray-700'
                }`}
                title={isSessionView ? 'Back to the image grid' : 'Browse by generation session'}
                type="button"
            >
                <Layers size={16} aria-hidden="true" />
                <span className="hidden sm:inline">
                    {isSessionView ? 'Grouped by session' : 'Group by session'}
                </span>
                <span className="sm:hidden">By session</span>
            </button>

            <div className="flex-1" />

            <div className="flex items-center gap-2">
                <button
                    onClick={() => navigate('/statistics')}
                    className="p-2 bg-gray-800 rounded-lg hover:bg-gray-700 text-gray-400 hover:text-white transition-colors"
                    title="View Statistics"
                    type="button"
                >
                    <BarChart3 size={20} aria-hidden="true" />
                </button>
                <button
                    onClick={onClearHistory}
                    className="p-2 bg-gray-800 rounded-lg hover:bg-gray-700 text-gray-400 hover:text-white transition-colors"
                    title="Clear Job History"
                    type="button"
                >
                    <Trash2 size={20} aria-hidden="true" />
                </button>
            </div>
        </div>
    );
}
