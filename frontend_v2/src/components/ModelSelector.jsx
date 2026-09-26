import { useState, useEffect, memo, useMemo, useCallback } from "react";
import { Loader2 } from "lucide-react";
import { createPortal } from "react-dom";
import { useInfiniteScroll } from "../hooks/useInfiniteScroll";
import { useInfiniteQuery } from "@tanstack/react-query";
import { filesApi } from "../api";
import { createStableSorter } from "../utils/seededRandom";
import TriggerBox from "./selector/TriggerBox";
import ModelFilterBar from "./selector/ModelFilterBar";
import ModelGridCard from "./selector/ModelGridCard";

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
}) {
  const [isOpen, setIsOpen] = useState(autoOpen);
  const [search, setSearch] = useState("");
  const [prevAutoOpen, setPrevAutoOpen] = useState(autoOpen);
  if (autoOpen !== prevAutoOpen) {
    setPrevAutoOpen(autoOpen);
    if (autoOpen) setIsOpen(true);
  }
  const [expandedModel, setExpandedModel] = useState(null);

  const [sortBy, setSortBy] = useState("name");
  const [filterBaseModel, setFilterBaseModel] = useState("all");
  const [filterType, setFilterType] = useState("all");
  const [showNSFW, setShowNSFW] = useState(true);

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetching,
    isFetchingNextPage,
    refetch,
  } = useInfiniteQuery({
    queryKey: ['models', directory, search, sortBy, filterBaseModel, filterType, showNSFW],
    queryFn: async ({ pageParam = 0, signal }) => {
      if (!directory) return { files: [] };
      const sortMap = { name: "name_asc", date: "date_desc", size: "size_desc", rating: "rating_desc" };
      const finalSort = sortBy.startsWith("random") ? sortBy : (sortMap[sortBy] || "name_asc");
      return filesApi.list({
        directory,
        limit: 50,
        offset: pageParam,
        sort: finalSort,
        search,
        base_model: filterBaseModel !== "all" ? filterBaseModel : undefined,
        model_type: filterType !== "all" ? filterType : undefined,
        show_nsfw: showNSFW,
      }, { signal });
    },
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((acc, page) => acc + (page.files?.length || 0), 0);
      return (lastPage.files?.length === 50) ? loaded : undefined;
    },
    enabled: isOpen && !!directory,
    staleTime: 5 * 60 * 1000,
  });

  const models = useMemo(() => {
    if (!directory && initialModels?.length > 0) return initialModels;
    return data?.pages.flatMap(page => page.files || []) || [];
  }, [data, directory, initialModels]);

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

  const getModelWithVersion = useCallback((model, version) => {
    if (!version) return model;
    const file = version.file || {};
    const versionImages = version.images || [];
    const selectedVersionPreviewId = version.civitai_version_id || version.id;
    const directPreviewImage = versionImages[0]?.url || model.preview;
    const proxyPreviewImage = model.civitai_id
      ? (() => {
          const params = new URLSearchParams({ image_index: "0" });
          if (selectedVersionPreviewId) {
            params.set("version_id", String(selectedVersionPreviewId));
          }
          return `/api/v2/models/preview/${model.civitai_id}?${params.toString()}`;
        })()
      : null;
    const previewImage = directPreviewImage || proxyPreviewImage;

    return {
      ...model,
      name: file.filename || model.name,
      display_name: model.display_name,
      civitai_id: model.civitai_id,
      preview: previewImage,
      base_model: version.base_model || model.base_model,
      trained_words: version.trained_words || [],
      default_version: version.name,
      version_description: version.description || "",
      selectedVersionId: version.id,
      selectedVersionPreviewId,
      size: file.size_kb ? file.size_kb * 1024 : model.size,
      _originalModel: model,
    };
  }, []);



  const handleClose = useCallback(() => {
    setIsOpen(false);
    if (onAutoOpenComplete) onAutoOpenComplete();
  }, [onAutoOpenComplete]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e) => { if (e.key === "Escape") handleClose(); };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, handleClose]);



  const filteredAndSortedModels = useMemo(() => {
    if (directory) return models;
    // Client side filtering ONLY if using initialModels (no directory provided)
    let result = [...models];
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (m) =>
          (m.name || '').toLowerCase().includes(q) ||
          (m.display_name || '').toLowerCase().includes(q)
      );
    }
    if (filterBaseModel !== "all" || filterType !== "all" || !showNSFW) {
      result = result.filter((m) => {
        if (filterBaseModel !== "all" && m.base_model !== filterBaseModel) return false;
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
  }, [models, directory, search, sortBy, filterBaseModel, filterType, showNSFW]);

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
  }, [getModelWithVersion, onVersionChange, onChange]);

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
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="model-selector-title"
          onClick={handleClose}
        >
          <div
            className="bg-gray-900 w-full max-w-4xl h-[80vh] rounded-2xl border border-gray-800 flex flex-col shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="p-4 border-b border-gray-800 space-y-3">
              <div className="flex justify-between items-center gap-4">
                <h3 id="model-selector-title" className="text-lg font-bold text-white">
                  Select {label}
                </h3>
                <button
                  onClick={handleClose}
                  className="p-2 hover:bg-gray-800 rounded-full text-gray-400 hover:text-white"
                  aria-label="Close modal"
                >
                  ✕
                </button>
              </div>
              <ModelFilterBar
                search={search}
                onSearchChange={setSearch}
                sortBy={sortBy}
                onSortChange={setSortBy}
                filterBaseModel={filterBaseModel}
                onFilterBaseModelChange={setFilterBaseModel}
                filterType={filterType}
                onFilterTypeChange={setFilterType}
                showNSFW={showNSFW}
                onShowNSFWChange={setShowNSFW}
                hasActiveFilters={filterBaseModel !== "all" || filterType !== "all" || !showNSFW}
                onClearFilters={() => { setFilterBaseModel("all"); setFilterType("all"); setShowNSFW(true); }}
              />
            </div>

            {/* Grid */}
            <div className="flex-1 overflow-y-auto p-4">
              {isFetching && !isFetchingNextPage ? (
                <div className="flex justify-center py-20 text-gray-500">
                  <Loader2 className="animate-spin" />
                </div>
              ) : filteredAndSortedModels.length === 0 ? (
                <div className="text-center py-20 text-gray-500">
                  {models.length === 0 ? "No models found" : "No models match your filters"}
                </div>
              ) : (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                  {filteredAndSortedModels.map((model) => (
                    <ModelGridCard
                      key={model.model_id || model.name}
                      model={model}
                      value={value}
                      isExpanded={expandedModel === model.model_id}
                      onExpand={setExpandedModel}
                      onSelect={(m) => { onChange(m); handleClose(); }}
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
