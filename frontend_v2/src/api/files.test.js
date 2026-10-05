/**
 * `assetsApi`'s method surface.
 *
 * `assetsApi.list` — `GET /api/v2/assets` — had zero callers: the gallery is on
 * `GET /api/v2/assets/facet`, which returns the same `items` / `has_more` /
 * `next_cursor` shape and adds `facets`, `sessions` and `total_matched`. Two
 * wrappers for one listing is the same shape as the `assetsApi.tags` /
 * `tagVocabulary` pair that `hookExportSurface.test.js` exists to prevent, and
 * it is the pair most likely to drift: someone reaching for "the assets list"
 * finds the plain one first and quietly gives up the facets the gallery needs.
 */
import { describe, it, expect } from 'vitest';

import { assetsApi, filesApi } from './files';

describe('assetsApi', () => {
    it('has one listing, the faceted one', () => {
        expect(assetsApi.list).toBeUndefined();
        expect(typeof assetsApi.facet).toBe('function');
    });

    it('names every method it does expose', () => {
        // Listed rather than counted: a sweep that counted would accept a new
        // wrapper without anyone deciding whether it is the one to keep.
        expect(Object.keys(assetsApi).sort()).toEqual([
            'addAssetTag',
            'assetTags',
            'dates',
            'facet',
            'removeAssetTag',
            'tagVocabulary',
        ]);
    });
});

describe('filesApi', () => {
    it('keeps the batch helpers the dashboard selection handlers call', () => {
        // `useDashboardSelection` reaches for exactly these two, and both take
        // the whole selection in one call: one ZIP for the batch, one
        // `files` array for the delete.
        expect(typeof filesApi.batchDownload).toBe('function');
        expect(typeof filesApi.deleteMultiple).toBe('function');
    });
});