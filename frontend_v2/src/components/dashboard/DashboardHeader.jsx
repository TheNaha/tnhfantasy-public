import { LayoutGrid, List, Square, LineChart, Check, RefreshCw, Wand2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { GALLERY_VIEW_MODES } from '../../store/settingsStore';
export function DashboardHeader({
    viewMode,
    setViewMode,
    gridCols,
    setGridCols,
    selectionMode,
    setSelectionMode,
    selectedFilesCount,
    onRefetch
}) {
    const navigate = useNavigate();

    return (
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <div>
                <h1 className="text-2xl md:text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-500">
                    Gallery
                </h1>
                <p className="text-gray-400 mt-1 text-sm">Your generations and active jobs</p>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
                <button
                    type="button"
                    onClick={() => navigate('/generate')}
                    data-testid="gallery-header-generate-btn"
                    aria-label="Switch to Simple Generator"
                    title="Switch to Simple Generator"
                    className="px-3.5 py-2 rounded-lg font-semibold text-sm bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white shadow-md shadow-blue-900/20 transition-all flex items-center gap-2"
                >
                    <Wand2 size={16} aria-hidden="true" />
                    <span>Generate</span>
                </button>

                <div className="bg-gray-800 rounded-lg p-1 flex gap-1">
                    {GALLERY_VIEW_MODES.map(mode => (
                        <button
                            key={mode}
                            onClick={() => setViewMode(mode)}
                            aria-label={`${mode.charAt(0).toUpperCase() + mode.slice(1)} View`}
                            className={`p-2 rounded-md transition-all ${viewMode === mode ? 'bg-gray-700 text-white shadow-sm' : 'text-gray-400 hover:text-white'}`}
                            type="button"
                            title={mode === 'timeline' ? 'Timeline View - Chronological history' : `${mode.charAt(0).toUpperCase() + mode.slice(1)} View`}
                        >
                            {mode === 'grid' ? <LayoutGrid size={18} aria-hidden="true" /> :
                                mode === 'list' ? <List size={18} aria-hidden="true" /> :
                                    mode === 'feed' ? <Square size={18} aria-hidden="true" /> :
                                        <LineChart size={18} aria-hidden="true" />}
                        </button>
                    ))}
                </div>

                {viewMode === 'grid' && (
                    <>
                        {/* Mobile quick-tap density buttons: 1x, 2x, 3x */}
                        <div className="flex sm:hidden items-center bg-gray-800 rounded-lg p-1 gap-0.5" role="group" aria-label="Mobile grid columns">
                            {[1, 2, 3].map((cols) => (
                                <button
                                    key={cols}
                                    type="button"
                                    onClick={() => setGridCols(cols)}
                                    aria-label={`${cols} column${cols > 1 ? 's' : ''}`}
                                    aria-pressed={Math.min(gridCols, 3) === cols}
                                    className={`no-touch-padding px-2.5 py-1.5 rounded-md text-xs font-bold transition-colors ${
                                        Math.min(gridCols, 3) === cols ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'
                                    }`}
                                >
                                    {cols}x
                                </button>
                            ))}
                        </div>

                        {/* Desktop slider */}
                        <div className="hidden sm:flex items-center gap-2 bg-gray-800 px-3 py-2 rounded-lg border border-gray-700">
                            <span className="text-xs text-gray-400 font-medium">Cols</span>
                            <input
                                type="range"
                                min="2"
                                max="8"
                                value={gridCols}
                                onChange={(e) => setGridCols(parseInt(e.target.value))}
                                className="w-20 h-1 bg-gray-600 rounded-lg appearance-none cursor-pointer accent-blue-500"
                                title="Adjust Grid Size"
                                aria-label={`Grid columns: ${gridCols}. Adjust to change number of columns`}
                            />
                            <span className="text-xs text-gray-400 font-medium">{gridCols}</span>
                        </div>
                    </>
                )}

                <div className="hidden sm:block h-6 w-px bg-gray-700" />

                <motion.button
                    whileHover={{ scale: 1.02 }}
                    whileTap={{ scale: 0.98 }}
                    onClick={() => setSelectionMode(!selectionMode)}
                    className={`px-4 py-2 rounded-lg font-medium transition-all flex items-center gap-2 ${selectionMode ? 'bg-blue-600 text-white hover:bg-blue-500' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'}`}
                    type="button"
                    aria-pressed={selectionMode}
                >
                    <Check size={16} aria-hidden="true" />
                    <span className="hidden sm:inline">{selectionMode ? `Selected (${selectedFilesCount})` : 'Select'}</span>
                    <span className="sm:hidden">{selectedFilesCount > 0 ? selectedFilesCount : 'Select'}</span>
                </motion.button>

                <button
                    onClick={onRefetch}
                    className="p-2 bg-gray-800 rounded-lg hover:bg-gray-700 text-gray-400 hover:text-white transition-colors"
                    title="Refresh gallery"
                    type="button"
                >
                    <RefreshCw size={20} aria-hidden="true" />
                </button>
            </div>
        </div>
    );
}
