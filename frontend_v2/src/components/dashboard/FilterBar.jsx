import { useState, useEffect, useId, memo } from 'react';
import { Filter, Calendar, Image as ImageIcon, Box, X, ChevronDown, Search } from 'lucide-react';
import { useDebounce } from '../../hooks/useDebounce';

// ⚡ Bolt: Wrap FilterBar in React.memo to prevent unnecessary re-renders when parent dashboard updates
export const FilterBar = memo(function FilterBar({ filters, onFilterChange }) {
    const [isOpen, setIsOpen] = useState(false);
    const [localFilters, setLocalFilters] = useState(filters);
    const [prevFilters, setPrevFilters] = useState(filters);

    // ⚡ Bolt: Derived state during render to avoid cascading re-renders and react-hooks/set-state-in-effect error
    if (filters !== prevFilters) {
        setPrevFilters(filters);
        setLocalFilters(filters);
    }

    const searchId = useId();
    const modelId = useId();
    const samplerId = useId();
    const aspectRatioId = useId();
    const filterPanelId = useId();

    // Debounced search value - waits 400ms after user stops typing
    const debouncedSearch = useDebounce(localFilters.search, 400);

    // Apply debounced search to parent
    useEffect(() => {
        if (debouncedSearch !== filters.search) {
            onFilterChange({ ...filters, search: debouncedSearch });
        }
    }, [debouncedSearch, filters, onFilterChange]);

    const handleApply = () => {
        onFilterChange(localFilters);
        setIsOpen(false);
    };

    const handleClear = () => {
        const cleared = {
            search: '',
            model: '',
            sampler: '',
            aspect_ratio: '',
            start_date: null,
            end_date: null
        };
        setLocalFilters(cleared);
        onFilterChange(cleared);
    };

    const handleChange = (key, value) => {
        setLocalFilters(prev => ({ ...prev, [key]: value }));
    };

    const activeFilterCount = Object.keys(filters).filter(k => filters[k] && k !== 'search').length;

    return (
        <div className="relative mb-6">
            <div className="flex gap-2">
                {/* Search Input */}
                <div className="relative flex-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={18} />
                    <input
                        id={searchId}
                        type="text"
                        aria-label="Search filters"
                        placeholder="Search images, prompts, models, parameters..."
                        value={localFilters.search || ''}
                        onChange={(e) => handleChange('search', e.target.value)}
                        className="w-full bg-gray-800 border border-gray-700 rounded-xl pl-10 pr-4 py-2.5 text-white focus:ring-2 focus:ring-blue-500 outline-none"
                    />
                </div>

                {/* Filter Toggle */}
                <button
                    onClick={() => setIsOpen(!isOpen)}
                    aria-expanded={isOpen}
                    aria-controls={filterPanelId}
                    aria-label="Toggle filters"
                    className={`flex items-center gap-2 px-4 py-2.5 rounded-xl border transition-colors ${isOpen || activeFilterCount > 0
                        ? 'bg-blue-600 border-blue-500 text-white'
                        : 'bg-gray-800 border-gray-700 text-gray-300 hover:bg-gray-700'
                        }`}
                >
                    <Filter size={18} />
                    <span className="hidden sm:inline">Filters</span>
                    {activeFilterCount > 0 && (
                        <span className="bg-white text-blue-600 text-xs font-bold px-1.5 py-0.5 rounded-full">
                            {activeFilterCount}
                        </span>
                    )}
                </button>
            </div>

            {/* Filter Panel */}
            {isOpen && (
                <div id={filterPanelId} className="absolute top-full left-0 right-0 mt-2 p-4 bg-gray-800 border border-gray-700 rounded-xl shadow-xl z-20 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">

                    {/* Model Filter */}
                    <div className="space-y-1">
                        <label htmlFor={modelId} className="text-xs font-medium text-gray-400 flex items-center gap-1">
                            <Box size={12} /> Model
                        </label>
                        <input
                            id={modelId}
                            type="text"
                            placeholder="e.g. SDXL, Pony"
                            value={localFilters.model || ''}
                            onChange={(e) => handleChange('model', e.target.value)}
                            className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-sm text-white"
                        />
                    </div>

                    {/* Sampler Filter */}
                    <div className="space-y-1">
                        <label htmlFor={samplerId} className="text-xs font-medium text-gray-400 flex items-center gap-1">
                            <ImageIcon size={12} /> Sampler
                        </label>
                        <select
                            id={samplerId}
                            value={localFilters.sampler || ''}
                            onChange={(e) => handleChange('sampler', e.target.value)}
                            className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-sm text-white"
                        >
                            <option value="">Any</option>
                            <option value="euler">Euler</option>
                            <option value="euler_ancestral">Euler a</option>
                            <option value="dpmpp_2m">DPM++ 2M</option>
                            <option value="dpmpp_sde">DPM++ SDE</option>
                            <option value="k_dpmpp_2m">K DPM++ 2M</option>
                        </select>
                    </div>

                    {/* Aspect Ratio */}
                    <div className="space-y-1">
                        <label htmlFor={aspectRatioId} className="text-xs font-medium text-gray-400 flex items-center gap-1">
                            <ImageIcon size={12} /> Aspect Ratio
                        </label>
                        <select
                            id={aspectRatioId}
                            value={localFilters.aspect_ratio || ''}
                            onChange={(e) => handleChange('aspect_ratio', e.target.value)}
                            className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-sm text-white"
                        >
                            <option value="">Any</option>
                            <option value="1:1">1:1 (Square)</option>
                            <option value="2:3">2:3 (Portrait)</option>
                            <option value="3:2">3:2 (Landscape)</option>
                            <option value="16:9">16:9 (Widescreen)</option>
                            <option value="9:16">9:16 (Mobile)</option>
                        </select>
                    </div>

                    {/* Date Range (Simplified as just "Since") */}
                    {/* Ideally we'd use a date picker, but native date input works for now */}
                    {/* 
                    <div className="space-y-1">
                        <label className="text-xs font-medium text-gray-400 flex items-center gap-1">
                            <Calendar size={12} /> Date
                        </label>
                        <input 
                            type="date" 
                            className="w-full bg-gray-900 border border-gray-600 rounded p-2 text-sm text-white"
                        />
                    </div>
                    */}

                    {/* Actions */}
                    <div className="md:col-span-2 lg:col-span-4 flex justify-end gap-2 pt-2 border-t border-gray-700">
                        <button
                            onClick={handleClear}
                            className="px-3 py-1.5 text-sm text-gray-400 hover:text-white transition-colors"
                        >
                            Clear All
                        </button>
                        <button
                            onClick={handleApply}
                            className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors"
                        >
                            Apply Filters
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
});
