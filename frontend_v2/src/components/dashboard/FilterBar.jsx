import { useState, useEffect, useId, memo } from 'react';
import { Search, X } from 'lucide-react';
import { useDebounce } from '../../hooks/useDebounce';

// ⚡ Bolt: Wrap FilterBar in React.memo to prevent unnecessary re-renders when parent dashboard updates
export const FilterBar = memo(function FilterBar({ filters, onFilterChange }) {
    const [localFilters, setLocalFilters] = useState(filters);
    const [prevFilters, setPrevFilters] = useState(filters);

    // ⚡ Bolt: Derived state during render to avoid cascading re-renders and react-hooks/set-state-in-effect error
    if (filters !== prevFilters) {
        setPrevFilters(filters);
        setLocalFilters(filters);
    }

    const searchId = useId();

    // Debounced search value - waits 400ms after user stops typing
    const debouncedSearch = useDebounce(localFilters.search, 400);

    // Apply debounced search to parent
    useEffect(() => {
        if (debouncedSearch !== filters.search) {
            onFilterChange({ ...filters, search: debouncedSearch });
        }
    }, [debouncedSearch, filters, onFilterChange]);

    const handleClear = () => {
        const cleared = { ...filters, search: '' };
        setLocalFilters(cleared);
        onFilterChange(cleared);
    };

    return (
        <div className="relative mb-6">
            <div className="flex flex-col md:flex-row gap-2">
                {/* Search Input */}
                <div className="relative w-full md:flex-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={18} />
                    <input
                        id={searchId}
                        type="text"
                        aria-label="Search filters"
                        placeholder="Search images, prompts, models, parameters..."
                        value={localFilters.search || ''}
                        onChange={(e) => setLocalFilters(prev => ({ ...prev, search: e.target.value }))}
                        className="w-full bg-gray-800 border border-gray-700 rounded-xl pl-10 pr-10 py-2.5 text-white focus:ring-2 focus:ring-blue-500 outline-none"
                    />
                    {filters.search && (
                        <button
                            onClick={handleClear}
                            aria-label="Clear search"
                            className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-white transition-colors"
                        >
                            <X size={16} />
                        </button>
                    )}
                </div>
                
                {/* Sort Dropdown */}
                <div className="flex items-center gap-2 w-full md:w-auto">
                    <div className="flex-1 md:flex-none md:w-48">
                        <select
                            aria-label="Sort images"
                            value={localFilters.sort?.startsWith('random') ? 'random' : (localFilters.sort || 'date_desc')}
                            onChange={(e) => {
                                let sortVal = e.target.value;
                                if (sortVal === 'random') {
                                    const savedSeed = localStorage.getItem('gallery_random_seed');
                                    const seed = savedSeed || Math.random().toString(36).substring(2, 10);
                                    if (!savedSeed) localStorage.setItem('gallery_random_seed', seed);
                                    sortVal = 'random:' + seed;
                                }
                                const newFilters = { ...localFilters, sort: sortVal };
                                setLocalFilters(newFilters);
                                onFilterChange(newFilters);
                            }}
                            className="w-full bg-gray-800 border border-gray-700 rounded-xl px-4 py-2.5 text-sm text-white focus:ring-2 focus:ring-blue-500 outline-none"
                        >
                            <option value="date_desc">Newest First</option>
                            <option value="date_asc">Oldest First</option>
                            <option value="random">Random</option>
                        </select>
                    </div>
                    {localFilters.sort?.startsWith('random') && (
                        <div className="flex items-center gap-1 bg-gray-800 border border-gray-700 rounded-xl p-1 h-[42px] flex-1 md:flex-none">
                            <input 
                                type="text"
                                aria-label="Random seed"
                                placeholder="Seed"
                                value={localFilters.sort.split(':')[1] || ''}
                                onChange={(e) => {
                                    const newSeed = e.target.value;
                                    localStorage.setItem('gallery_random_seed', newSeed);
                                    const newFilters = { ...localFilters, sort: 'random:' + newSeed };
                                    setLocalFilters(newFilters);
                                    onFilterChange(newFilters);
                                }}
                                className="w-full md:w-24 min-w-0 bg-transparent border-none text-sm text-gray-300 px-2 outline-none focus:ring-0"
                            />
                            <button
                                onClick={() => {
                                    const newSeed = Math.random().toString(36).substring(2, 10);
                                    localStorage.setItem('gallery_random_seed', newSeed);
                                    const newFilters = { ...localFilters, sort: 'random:' + newSeed };
                                    setLocalFilters(newFilters);
                                    onFilterChange(newFilters);
                                }}
                                title="Re-roll random seed"
                                className="p-1.5 text-gray-400 hover:text-white rounded-lg hover:bg-gray-700 transition-colors"
                            >
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                                </svg>
                            </button>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
});
