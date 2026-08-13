import { Search } from 'lucide-react';

export default function ModelFilterBar({
  search,
  onSearchChange,
  sortBy,
  onSortChange,
  filterBaseModel,
  onFilterBaseModelChange,
  filterType,
  onFilterTypeChange,
  showNSFW,
  onShowNSFWChange,
  hasActiveFilters,
  onClearFilters,
}) {
  return (
    <>
      {/* Search Bar */}
      <div className="relative">
        <Search
          className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500"
          size={18}
        />
        <input
          type="text"
          placeholder="Search models by name, tags, description..."
          aria-label="Search models"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="w-full bg-gray-800 border border-gray-700 rounded-full pl-10 pr-4 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
          autoFocus
        />
      </div>

      {/* Sort and Filter */}
      <div className="flex gap-2 flex-wrap">
        <div className="flex items-center gap-1">
          <select
            value={sortBy?.startsWith('random') ? 'random' : sortBy}
            onChange={(e) => {
                let val = e.target.value;
                if (val === 'random') {
                    val = 'random:' + Math.random().toString(36).substring(2, 10);
                }
                onSortChange(val);
            }}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
          >
            <option value="name">Sort: Name</option>
            <option value="date">Sort: Date</option>
            <option value="size">Sort: Size</option>
            <option value="rating">Sort: Rating</option>
            <option value="random">Sort: Random</option>
          </select>
          {sortBy?.startsWith('random') && (
            <button
                onClick={() => onSortChange('random:' + Math.random().toString(36).substring(2, 10))}
                title="Re-roll random seed"
                className="p-1.5 bg-gray-800 border border-gray-700 rounded-lg text-gray-400 hover:text-white hover:bg-gray-700 transition-colors"
            >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
            </button>
          )}
        </div>

        <select
          value={filterBaseModel}
          onChange={(e) => onFilterBaseModelChange(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
        >
          <option value="all">All Base Models</option>
          <option value="SD 1.5">SD 1.5</option>
          <option value="SDXL 1.0">SDXL</option>
          <option value="SD 3">SD 3</option>
          <option value="Pony">Pony</option>
        </select>

        <select
          value={filterType}
          onChange={(e) => onFilterTypeChange(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
        >
          <option value="all">All Types</option>
          <option value="Checkpoint">Checkpoint</option>
          <option value="LORA">LoRA</option>
          <option value="TextualInversion">Embedding</option>
        </select>

        <label className="flex items-center gap-2 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white cursor-pointer hover:border-blue-500">
          <input
            type="checkbox"
            checked={showNSFW}
            onChange={(e) => onShowNSFWChange(e.target.checked)}
            className="rounded w-3 h-3"
          />
          Show NSFW
        </label>

        {hasActiveFilters && (
          <button
            onClick={onClearFilters}
            className="bg-red-900/30 border border-red-800 rounded-lg px-3 py-1.5 text-xs text-red-300 hover:bg-red-900/50"
            aria-label="Clear all filters"
          >
            Clear Filters
          </button>
        )}
      </div>
    </>
  );
}
