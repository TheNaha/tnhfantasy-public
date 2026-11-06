import { useState, useEffect, memo, useMemo, useCallback, useRef } from "react";
import { Loader2 } from "lucide-react";
import { createPortal } from "react-dom";
import { modelListKey } from "../constants/queryKeys";
import { useInfiniteScroll } from "../hooks/useInfiniteScroll";
import { useInfiniteQuery } from "@tanstack/react-query";
import { filesApi } from "../api";
import { createStableSorter } from "../utils/seededRandom";
import { nextOffsetPageParam } from "../utils/pagination";
import { getModelWithVersion } from "../utils/modelDisplay";
import TriggerBox from "./selector/TriggerBox";
import ModelFilterBar from "./selector/ModelFilterBar";
import ModelGridCard from "./selector/ModelGridCard";
import { QueryErrorState } from "./common/QueryState";

function getSelectorSaved(directory, key, defaultValue) {
  try {
    const dirKey = directory ? directory.replace(/[^a-zA-Z0-9_-]/g, "_") : "default";
    const item = localStorage.getItem(`model_selector_${dirKey}_${key}`);
    return item !== null ? JSON.parse(item) : defaultValue;
  } catch {
    return defaultValue;
  }
}

function setSelectorSaved(directory, key, value) {
  try {
    const dirKey = directory ? directory.replace(/[^a-zA-Z0-9_-]/g, "_") : "default";
    localStorage.setItem(`model_selector_${dirKey}_${key}`, JSON.stringify(value));
  } catch {
    // ignore quota errors
  }
}

function clearSelectorSaved(directory) {
  try {
    const dirKey = directory ? directory.replace(/[^a-zA-Z0-9_-]/g, "_") : "default";
    ["search", "sort", "baseModel", "type", "nsfw", "tags", "scroll"].forEach((key) => {
      localStorage.removeItem(`model_selector_${dirKey}_${key}`);
    });
  } catch {
    // ignore
  }
}

// One sorter per seed, kept at module scope so its key cache survives
// re-renders. createStableSorter memoises the hash per item identity, which is
// the whole point: without this the cache died with the render.
const _seededSorters = new Map();
function getSeededSorter(seed) {
  let sorter = _seededSorters.get(seed);
  if (!sorter) {
    sorter = createStableSorter(seed);
    _seededSorters.set(seed, sorter);
  }
  return sorter;
}

const ModelSelector = memo(function ModelSelector({
  label,
  value,
  selectedModel: externalSelectedModel,
  preview,
  metadata,
  onChange,
  directory,
  initialModels = [],
  autoOpen = false,
  onAutoOpenComplete,
  onVersionChange,
  onInfoClick,
  onAddTriggerWords,
  onApplySDXLSettings,
  showAvailabilityBadge = false,
  providers = [],
  providersLoading = false,
  activeCheckpoint = null,
}) {
  const [isOpen, setIsOpen] = useState(autoOpen);
  const [search, setSearch] = useState(() => getSelectorSaved(directory, "search", ""));
  const [prevAutoOpen, setPrevAutoOpen] = useState(autoOpen);
  if (autoOpen !== prevAutoOpen) {
    setPrevAutoOpen(autoOpen);
    if (autoOpen) setIsOpen(true);
  }
  const [expandedModel, setExpandedModel] = useState(null);

  const [sortBy, setSortBy] = useState(() => getSelectorSaved(directory, "sort", "name"));
  const [filterBaseModel, setFilterBaseModel] = useState(() => getSelectorSaved(directory, "baseModel", "all"));
  const [filterType, setFilterType] = useState(() => getSelectorSaved(directory, "type", "all"));
  const [showNSFW, setShowNSFW] = useState(() => getSelectorSaved(directory, "nsfw", true));
  // Tag filtering is server-side (GET /api/files?tags=a,b applies AND across the
  // list). This was missing entirely, so the one place a user picks the model
  // they are about to generate with could not filter by tag — which is exactly
  // "I have a hard time to find a LORA for a specific character".
  const [selectedTags, setSelectedTags] = useState(() => getSelectorSaved(directory, "tags", []));

  const [prevDir, setPrevDir] = useState(directory);
  if (directory !== prevDir) {
    setPrevDir(directory);
    scrollRestoredRef.current = false;
    setSearch(getSelectorSaved(directory, "search", ""));
    setSortBy(getSelectorSaved(directory, "sort", "name"));
    setFilterBaseModel(getSelectorSaved(directory, "baseModel", "all"));
    setFilterType(getSelectorSaved(directory, "type", "all"));
    setShowNSFW(getSelectorSaved(directory, "nsfw", true));
    setSelectedTags(getSelectorSaved(directory, "tags", []));
  }

  const gridContainerRef = useRef(null);
  const isRestoringScrollRef = useRef(false);
  const scrollRestoredRef = useRef(false);

  const handleSearchChange = useCallback((newSearch) => {
    setSearch(newSearch);
    setSelectorSaved(directory, "search", newSearch);
    setSelectorSaved(directory, "scroll", 0);
    if (gridContainerRef.current) gridContainerRef.current.scrollTop = 0;
  }, [directory]);

  const handleSortChange = useCallback((newSort) => {
    setSortBy(newSort);
    setSelectorSaved(directory, "sort", newSort);
    setSelectorSaved(directory, "scroll", 0);
    if (gridContainerRef.current) gridContainerRef.current.scrollTop = 0;
  }, [directory]);

  const handleFilterBaseModelChange = useCallback((newBaseModel) => {
    setFilterBaseModel(newBaseModel);
    setSelectorSaved(directory, "baseModel", newBaseModel);
    setSelectorSaved(directory, "scroll", 0);
    if (gridContainerRef.current) gridContainerRef.current.scrollTop = 0;
  }, [directory]);

  const handleFilterTypeChange = useCallback((newType) => {
    setFilterType(newType);
    setSelectorSaved(directory, "type", newType);
    setSelectorSaved(directory, "scroll", 0);
    if (gridContainerRef.current) gridContainerRef.current.scrollTop = 0;
  }, [directory]);

  const handleShowNSFWChange = useCallback((newNsfw) => {
    setShowNSFW(newNsfw);
    setSelectorSaved(directory, "nsfw", newNsfw);
    setSelectorSaved(directory, "scroll", 0);
    if (gridContainerRef.current) gridContainerRef.current.scrollTop = 0;
  }, [directory]);

  const handleSelectedTagsChange = useCallback((newTags) => {
    setSelectedTags(newTags);
    setSelectorSaved(directory, "tags", newTags);
    setSelectorSaved(directory, "scroll", 0);
    if (gridContainerRef.current) gridContainerRef.current.scrollTop = 0;
  }, [directory]);

  const handleClearFilters = useCallback(() => {
    setSearch("");
    setFilterBaseModel("all");
    setFilterType("all");
    setShowNSFW(true);
    setSelectedTags([]);
    clearSelectorSaved(directory);
    if (gridContainerRef.current) gridContainerRef.current.scrollTop = 0;
  }, [directory]);

  const handleScroll = useCallback((e) => {
    if (isRestoringScrollRef.current) return;
    const top = e.currentTarget.scrollTop;
    setSelectorSaved(directory, "scroll", top);
  }, [directory]);

  // The sort is normalised BEFORE the key is built, and the same normalised
  // value is used for the request. It used to be built from the raw UI value
  // ('name'), so this component's keys did not match `modelListKey`'s documented
  // 'name_asc' contract — fine while the two pickers are separated by
  // `directory`, a collision the moment they are unified.
  const SORT_MAP = {
    name: "name_asc",
    date: "date_updated_desc",
    date_added: "date_added_desc",
    date_updated: "date_updated_desc",
    size: "size_desc",
    rating: "rating_desc",
  };
  const finalSort = sortBy.startsWith("random") ? sortBy : (SORT_MAP[sortBy] || "name_asc");

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetching,
    isFetchingNextPage,
    isError,
    error,
    refetch,
  } = useInfiniteQuery({
    // `baseModel` / `modelType`, not `filterBaseModel` / `filterType` — the
    // factory destructures those two names, so the filters were dropped on the
    // floor and both fell back to 'all'. The query key therefore never changed
    // when either dropdown was used, so `useInfiniteQuery` neither refetched
    // nor cleared: the base-model and model-type filters in the generator's
    // model picker were dead controls.
    queryKey: modelListKey({ directory, search, sortBy: finalSort, baseModel: filterBaseModel, modelType: filterType, showNSFW, selectedTags, pageSize: 50 }),
    queryFn: async ({ pageParam = 0, signal }) => {
      if (!directory) return { files: [] };
      return filesApi.list({
        directory,
        limit: 50,
        offset: pageParam,
        sort: finalSort,
        search,
        base_model: filterBaseModel !== "all" ? filterBaseModel : undefined,
        model_type: filterType !== "all" ? filterType : undefined,
        show_nsfw: showNSFW,
        tags: selectedTags.length > 0 ? selectedTags.join(",") : undefined,
      }, { signal });
    },
    getNextPageParam: nextOffsetPageParam,
    enabled: isOpen && !!directory,
    staleTime: 5 * 60 * 1000,
  });

  const models = useMemo(() => {
    if (!directory && initialModels?.length > 0) return initialModels;
    return data?.pages.flatMap(page => page.files || []) || [];
  }, [data, directory, initialModels]);

  // Tags offered in the dropdown: everything on the loaded models, plus the
  // current selection so a selected tag is always representable. Deliberately
  // NOT accumulated across queries — React Query drops `data` while a new key
  // resolves, and the dropdown narrowing to the selected tags for that one
  // render is correct; accumulating would need a ref written during render,
  // which the react-hooks lint rules reject here.
  const availableTags = useMemo(() => {
    const tags = new Set(selectedTags);
    models.forEach(m => (m.tags || []).forEach(t => tags.add(t)));
    return Array.from(tags).sort();
  }, [models, selectedTags]);

  const internalSelectedModel = useMemo(() => {
    if (!externalSelectedModel && value) {
      const found = models.find((m) => m.name === value);
      if (found) {
        return { ...found, preview: found.preview || preview, metadata: found.metadata || metadata };
      }
      return { name: value, preview, metadata };
    }
    return null;
  }, [value, models, preview, metadata, externalSelectedModel]);

  const selectedModel = useMemo(() => {
    let sm = externalSelectedModel || internalSelectedModel;
    if (sm && (!sm.versions || sm.versions.length === 0)) {
       const matchingModel = models.find(m => m.name === sm.name || m.name === sm._originalModel?.name || m.display_name === sm.display_name);
       if (matchingModel) {
          sm = { 
            ...matchingModel, 
            ...sm, 
            versions: matchingModel.versions,
            civitai_id: sm.civitai_id || matchingModel.civitai_id,
            preview: sm.preview || matchingModel.preview,
            base_model: sm.base_model || matchingModel.base_model
          };
       }
    }
    return sm;
  }, [externalSelectedModel, internalSelectedModel, models]);





  const handleClose = useCallback(() => {
    if (gridContainerRef.current && !isRestoringScrollRef.current) {
      setSelectorSaved(directory, "scroll", gridContainerRef.current.scrollTop);
    }
    setIsOpen(false);
    if (onAutoOpenComplete) onAutoOpenComplete();
  }, [directory, onAutoOpenComplete]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e) => { if (e.key === "Escape") handleClose(); };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, handleClose]);



  const filteredAndSortedModels = useMemo(() => {
    if (directory) return models;
    // Client side filtering ONLY if using initialModels (no directory provided).
    // Mirrors what the backend now does for the server path, so the two do not
    // disagree: name, display name, tags, trained words and description.
    let result = [...models];
    if (search) {
      const q = search.toLowerCase();
      const haystack = (m) => [
        m.name,
        m.display_name,
        m.description,
        ...(m.tags || []),
        ...(m.trained_words || []),
      ].filter(Boolean).join(" ").toLowerCase();
      result = result.filter(m => haystack(m).includes(q));
    }
    if (selectedTags.length > 0) {
      result = result.filter(m => selectedTags.every(t => (m.tags || []).includes(t)));
    }
    if (filterBaseModel !== "all" || filterType !== "all" || !showNSFW) {
      result = result.filter((m) => {
        if (filterBaseModel !== "all") {
          const mBase = m.base_model || m.baseModel || "";
          const target = filterBaseModel.toLowerCase().replace(/[^a-z0-9]/g, "");
          const cleanM = mBase.toLowerCase().replace(/[^a-z0-9]/g, "");
          if (filterBaseModel === "SDXL 1.0" || filterBaseModel === "SDXL") {
            if (!cleanM.includes("sdxl")) return false;
          } else if (filterBaseModel === "Pony") {
            if (!cleanM.includes("pony")) return false;
          } else if (filterBaseModel === "Flux") {
            if (!cleanM.includes("flux")) return false;
          } else if (filterBaseModel === "Illustrious") {
            if (!cleanM.includes("illustrious") && !cleanM.includes("noob")) return false;
          } else if (filterBaseModel === "NoobAI") {
            if (!cleanM.includes("noob")) return false;
          } else if (!cleanM.includes(target) && !target.includes(cleanM)) {
            return false;
          }
        }
        if (filterType !== "all" && m.type !== filterType) return false;
        if (!showNSFW && m.nsfw) return false;
        return true;
      });
    }
    if (sortBy?.startsWith("random")) {
      // Route through createStableSorter instead of hashing inside the
      // comparator: Array.prototype.sort calls the comparator O(n log n) times
      // and stableRandomKey() re-runs an FNV-1a pass over the model name every
      // time, so a 500-model list paid ~4500 string hashes per re-sort. The
      // sorter computes each key once and memoises it, and the sorter itself is
      // memoised per seed so the cache survives re-renders.
      const seed = sortBy.split(":")[1] || "stable_random_seed";
      return getSeededSorter(seed)(result, (m) => m.name);
    }
    result.sort((a, b) => {
      const getVal = (v) => v || 0;
      switch (sortBy) {
        case "name": return (a.name || "").localeCompare(b.name || "");
        case "date": return getVal(b.modified_time) - getVal(a.modified_time);
        case "size": return getVal(b.size) - getVal(a.size);
        case "rating": return getVal(b.stats?.thumbsUp || b.stats?.thumbsUpCount) - getVal(a.stats?.thumbsUp || a.stats?.thumbsUpCount);
        default: return 0;
      }
    });
    return result;
  }, [models, directory, search, sortBy, filterBaseModel, filterType, showNSFW, selectedTags]);

  useEffect(() => {
    if (!isOpen) {
      scrollRestoredRef.current = false;
      return;
    }
    if (scrollRestoredRef.current) return;
    const savedScroll = getSelectorSaved(directory, "scroll", 0);
    if (!savedScroll || savedScroll <= 0) {
      scrollRestoredRef.current = true;
      return;
    }
    const el = gridContainerRef.current;
    if (el && el.scrollHeight > el.clientHeight) {
      isRestoringScrollRef.current = true;
      el.scrollTop = savedScroll;
      scrollRestoredRef.current = true;
      requestAnimationFrame(() => {
        isRestoringScrollRef.current = false;
      });
    }
  }, [isOpen, directory, filteredAndSortedModels.length]);

  const loadMore = useCallback(() => {
    if (hasNextPage && !isFetching) fetchNextPage();
  }, [hasNextPage, isFetching, fetchNextPage]);

  const sentinelRef = useInfiniteScroll({
    hasMore: hasNextPage && !isFetching,
    onLoadMore: loadMore,
    loading: isFetchingNextPage,
    rootMargin: "300px",
  });

  const handleVersionSelect = useCallback((model, version) => {
    const modelWithVersion = getModelWithVersion(model, version);
    if (onVersionChange) onVersionChange(modelWithVersion);
    else onChange(modelWithVersion);
  }, [onVersionChange, onChange]);

  // `ModelGridCard` is memoised, and a fresh arrow prop per render defeats it
  // exactly as thoroughly as not memoising the card at all: with a 200-model
  // grid, every keystroke in the search box re-rendered every card even when
  // the model, the filters and the expanded id were all unchanged.
  const handleSelectAndClose = useCallback((model) => {
    onChange(model);
    handleClose();
  }, [onChange, handleClose]);

  return (
    <div className="space-y-2">
      <label className="block text-xs font-medium text-gray-500">{label}</label>

      {/* Trigger Box */}
      <TriggerBox
        label={label}
        selectedModel={selectedModel}
        isOpen={isOpen}
        onOpen={() => setIsOpen(true)}
        onChange={onChange}
        onVersionChange={onVersionChange}
        getModelWithVersion={getModelWithVersion}
        onInfoClick={onInfoClick}
        onAddTriggerWords={onAddTriggerWords}
        directory={directory}
        refetch={refetch}
      />

      {/* Modal */}
      {isOpen && createPortal(
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-end sm:items-center justify-center p-0 sm:p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="model-selector-title"
          onClick={handleClose}
        >
          <div
            className="bg-gray-900 w-full sm:max-w-4xl h-[92vh] sm:h-[85vh] rounded-t-2xl sm:rounded-2xl border-t sm:border border-gray-800 flex flex-col shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="p-3 sm:p-4 border-b border-gray-800 space-y-2.5 sm:space-y-3 shrink-0">
              <div className="flex justify-between items-center gap-3">
                <h3 id="model-selector-title" className="text-base sm:text-lg font-bold text-white truncate">
                  Select {label}
                </h3>
                <button
                  onClick={handleClose}
                  className="p-1.5 sm:p-2 hover:bg-gray-800 rounded-full text-gray-400 hover:text-white transition-colors"
                  aria-label="Close modal"
                >
                  ✕
                </button>
              </div>
              <ModelFilterBar
                search={search}
                onSearchChange={handleSearchChange}
                sortBy={sortBy}
                onSortChange={handleSortChange}
                filterBaseModel={filterBaseModel}
                onFilterBaseModelChange={handleFilterBaseModelChange}
                filterType={filterType}
                onFilterTypeChange={handleFilterTypeChange}
                showNSFW={showNSFW}
                onShowNSFWChange={handleShowNSFWChange}
                availableTags={availableTags}
                selectedTags={selectedTags}
                onSelectedTagsChange={handleSelectedTagsChange}
                hasActiveFilters={search.trim() !== "" || filterBaseModel !== "all" || filterType !== "all" || !showNSFW || selectedTags.length > 0}
                onClearFilters={handleClearFilters}
                tagsError={isError ? error : null}
                onRetryTags={refetch}
                activeCheckpoint={activeCheckpoint}
              />
            </div>

            {/* Grid */}
            <div
              ref={gridContainerRef}
              onScroll={handleScroll}
              className="flex-1 overflow-y-auto p-3 sm:p-4"
            >
              {isFetching && !isFetchingNextPage ? (
                <div className="flex justify-center py-20 text-gray-500">
                  <Loader2 className="animate-spin" />
                </div>
              ) : isError ? (
                /* Not the empty state. A failed GET /api/files leaves `models`
                   at its `|| []` default, so `filteredAndSortedModels.length ===
                   0` was satisfied by an outage and printed "No models found"
                   next to a picker for a directory that holds hundreds of
                   files. Only reachable when the query actually ran, so the
                   `initialModels` path (no `directory`, query disabled) cannot
                   land here. */
                <QueryErrorState
                  noun={`${label || 'models'} in this picker`}
                  error={error}
                  onRetry={refetch}
                  className="text-left"
                />
              ) : filteredAndSortedModels.length === 0 ? (
                <div className="text-center py-20 text-gray-500">
                  {models.length === 0 ? "No models found" : "No models match your filters"}
                </div>
              ) : (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2.5 sm:gap-4">
                  {filteredAndSortedModels.map((model) => (
                    <ModelGridCard
                      key={model.model_id || model.name}
                      model={model}
                      value={value}
                      isExpanded={expandedModel === model.model_id}
                      onExpand={setExpandedModel}
                      onSelect={handleSelectAndClose}
                      onVersionSelect={handleVersionSelect}
                      onAddTriggerWords={onAddTriggerWords}
                      onApplySDXLSettings={onApplySDXLSettings}
                      showAvailabilityBadge={showAvailabilityBadge}
                      providers={providers}
                      providersLoading={providersLoading}
                    />
                  ))}
                </div>
              )}

              <div ref={sentinelRef} className="h-4" />

              {isFetchingNextPage && (
                <div className="flex justify-center py-4">
                  <Loader2 className="animate-spin text-gray-400" size={24} />
                </div>
              )}
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
});

export default ModelSelector;
