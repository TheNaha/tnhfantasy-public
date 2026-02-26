## 2026-02-23 - Scalability: Avoid Full Table Scans for Queue Positions
**Learning:** Fetching all pending jobs (`self.repo.get_pending()`) to calculate queue positions causes O(N) memory usage and database load on every paginated request, scaling linearly with queue size.
**Action:** Replace bulk fetches with targeted `COUNT(*)` queries for the specific items on the current page. While this introduces N+1 queries (where N is page size), it bounds memory usage and database load to O(Page Size), which is vastly more scalable for large queues.
