## 2026-02-23 - Scalability: Avoid Full Table Scans for Queue Positions
**Learning:** Fetching all pending jobs (`self.repo.get_pending()`) to calculate queue positions causes O(N) memory usage and database load on every paginated request, scaling linearly with queue size.
**Action:** Replace bulk fetches with targeted `COUNT(*)` queries for the specific items on the current page. While this introduces N+1 queries (where N is page size), it bounds memory usage and database load to O(Page Size), which is vastly more scalable for large queues.

## 2026-03-03 - IntersectionObserver Instance Overhead
**Learning:** Creating a `new IntersectionObserver()` inside every instance of a frequently rendered component (like `ProgressiveImage` in a gallery grid) causes significant memory overhead and main-thread blocking, drastically degrading scrolling performance as hundreds of observers are instantiated simultaneously.
**Action:** Extract lazy-loading logic into a shared module using a single singleton `IntersectionObserver` that maps observed DOM elements to their specific callbacks using a `WeakMap`, allowing O(1) tracking without memory leaks.
