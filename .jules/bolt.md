## 2026-02-23 - Scalability: Avoid Full Table Scans for Queue Positions
**Learning:** Fetching all pending jobs (`self.repo.get_pending()`) to calculate queue positions causes O(N) memory usage and database load on every paginated request, scaling linearly with queue size.
**Action:** Replace bulk fetches with targeted `COUNT(*)` queries for the specific items on the current page. While this introduces N+1 queries (where N is page size), it bounds memory usage and database load to O(Page Size), which is vastly more scalable for large queues.

## 2026-03-03 - IntersectionObserver Instance Overhead
**Learning:** Creating a `new IntersectionObserver()` inside every instance of a frequently rendered component (like `ProgressiveImage` in a gallery grid) causes significant memory overhead and main-thread blocking, drastically degrading scrolling performance as hundreds of observers are instantiated simultaneously.
**Action:** Extract lazy-loading logic into a shared module using a single singleton `IntersectionObserver` that maps observed DOM elements to their specific callbacks using a `WeakMap`, allowing O(1) tracking without memory leaks.

## 2024-05-18 - React.memo Broken By Inline Arrow Functions
**Learning:** In components like `TimelineView` rendering `JobCard`, passing inline arrow functions (e.g. `onClick={() => onJobClick?.(item)}`) breaks the child's `React.memo` optimization, causing unnecessary re-renders inside list/grid containers on every update.
**Action:** When passing callbacks to memoized components, ensure stable function references are passed directly (e.g. `onClick={onJobClick}`), and have the child component safely handle the invocation (e.g. with `useCallback` around its own interaction handlers).

## 2024-05-19 - Memoize Large Container Components
**Learning:** Large, conditionally rendered container components (like `GroupedDashboardContent` in a dashboard view) that map over large arrays and render many complex child components (like `JobCard`, `ImageGroup`, `FeedCard`) can cause significant rendering overhead if they are not memoized and their parent component re-renders frequently due to unrelated state changes.
**Action:** Wrap such components in `React.memo()` to prevent unnecessary re-renders when their props haven't changed.

## 2024-05-30 - O(N²) Performance Bottleneck in Dashboard Item Processing
**Learning:** Using `Array.prototype.find()` inside a loop over another collection (e.g., matching jobs to images by filename) creates an O(N²) complexity that severely degrades frontend performance as the gallery grows, potentially locking the main thread.
**Action:** Always pre-compute a Hash Map (e.g., `new Map()`) keyed by the matching property before the loop to achieve O(1) lookups and O(N) overall complexity.

## 2024-06-05 - Hidden O(N²) Loop in Array Searches for Duplicate Prevention
**Learning:** Using `Array.prototype.find()` inside an array iteration (e.g. processing dashboard items) to check if an item was already added creates a hidden O(N²) performance bottleneck. When the logic already maintains a `Set` (e.g., `usedJobIds`) to prevent duplicate processing, the `.find` call is guaranteed to fail (returning `undefined`), making the O(N) scan completely redundant and purely wasteful.
**Action:** Trust your existing `Set` or `Map` data structures. If a `Set` guarantees an item hasn't been processed, remove any subsequent `.find()` checks for that item in the result array, transforming O(N²) complexity into O(N).

## 2024-06-12 - O(N²) Bottleneck in State Change Comparisons
**Learning:** In global store subscriptions (like `useJobStore.subscribe`), comparing large current state arrays against large previous state arrays using `.filter(item => !prevState.items.find(prev => prev.id === item.id))` introduces an O(N * M) performance bottleneck that blocks the main thread on every state update.
**Action:** Always pre-compute a Hash Set (e.g., `new Set(prevState.items.map(...))`) of the previous state identifiers before the filtering loop. This transforms the O(N * M) comparison into an efficient O(N + M) operation via O(1) `Set.has()` lookups.

## 2024-06-25 - Prevent O(N) Processing Overhead with `reduce`
**Learning:** In React frontend components, executing multiple sequential `.filter()` operations over the same large array to calculate different statistics (e.g. counting jobs, images, and successes in `TimelineView`) introduces unnecessary O(N) processing overhead during render loops.
**Action:** Replace multiple `.filter()` passes with a single `reduce()` operation to pre-compute all required statistics in a single O(N) pass, significantly improving rendering performance for large data sets.
## 2024-06-18 - Avoid O(N) Array Operations Inside Render Loops
**Learning:** Calling array methods like `.filter()` multiple times inside the map function of a render loop (e.g. calculating stats for grouped timeline items) creates hidden array allocations and O(N) execution paths that run every single time the component renders, degrading performance when interacting with large datasets.
**Action:** Pre-compute metadata or statistics during the initial data transformation pass (like inside a `useMemo` that groups data) by keeping running totals in the accumulator object. This changes O(N * renders) complexity into a single O(1) increment per item during the memoized data preparation phase.

## 2026-04-06 - O(N*M) Bottleneck in Array Filtering
**Learning:** Using `Array.prototype.includes()` inside a `.filter()` operation (e.g., removing multiple images from a collection) introduces an O(N*M) performance bottleneck, as it scans the target array on every iteration.
**Action:** Always pre-compute a `Set` of the items to be checked against before the filtering loop. This transforms the O(N*M) comparison into an efficient O(N) operation via O(1) `Set.has()` lookups.
