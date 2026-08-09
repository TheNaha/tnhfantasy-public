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
            </div>
        </div>
    );
});
