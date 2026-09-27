import { describe, it, expect, beforeEach } from 'vitest';

// Mock zustand persist middleware to avoid localStorage in tests
vi.mock('zustand/middleware', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        persist: (fn) => fn,
    };
});

const DEFAULT_SETTINGS = {
    ui: {
        defaultViewMode: 'grid',
        defaultGridColumns: 4,
        toastSuccessDuration: 3000,
        toastErrorDuration: 4000,
        animationDuration: 200,
        queryStaleTime: 300000,
        queryCacheTime: 600000
    },
    gallery: {
        itemsPerPage: 20,
        autoRefreshOnJobComplete: true,
        silentRefresh: true
    },
    models: {
        itemsPerPage: 20,
        autoRemoveDownloads: true
    },
    generator: {
        autoRandomizeSeed: true,
        redirectAfterGenerate: true,
        redirectDelay: 1000
    }
};

describe('useSettingsStore', () => {
    let useSettingsStore;

    beforeEach(async () => {
        vi.resetModules();
        const mod = await import('../store/settingsStore.js');
        useSettingsStore = mod.default;
        // Reset to defaults before each test
        useSettingsStore.getState().resetSettings();
    });

    describe('initial state', () => {
        it('has default UI settings', () => {
            const { settings } = useSettingsStore.getState();
            expect(settings.ui.defaultViewMode).toBe('grid');
            expect(settings.ui.defaultGridColumns).toBe(4);
            expect(settings.ui.toastSuccessDuration).toBe(3000);
        });

        it('has default gallery settings', () => {
            const { settings } = useSettingsStore.getState();
            expect(settings.gallery.itemsPerPage).toBe(20);
            expect(settings.gallery.autoRefreshOnJobComplete).toBe(true);
        });

        it('has default models settings', () => {
            const { settings } = useSettingsStore.getState();
            expect(settings.models.itemsPerPage).toBe(20);
            expect(settings.models.autoRemoveDownloads).toBe(true);
        });

        it('has default generator settings', () => {
            const { settings } = useSettingsStore.getState();
            expect(settings.generator.autoRandomizeSeed).toBe(true);
            expect(settings.generator.redirectAfterGenerate).toBe(true);
        });
    });

    describe('updateSetting', () => {
        it('updates a single setting in a category', () => {
            const { updateSetting } = useSettingsStore.getState();
            updateSetting('ui', 'defaultViewMode', 'list');
            const { settings } = useSettingsStore.getState();
            expect(settings.ui.defaultViewMode).toBe('list');
        });

        it('does not affect other settings in the same category', () => {
            const { updateSetting } = useSettingsStore.getState();
            updateSetting('ui', 'defaultViewMode', 'list');
            const { settings } = useSettingsStore.getState();
            expect(settings.ui.defaultGridColumns).toBe(4);
        });

        it('does not affect other categories', () => {
            const { updateSetting } = useSettingsStore.getState();
            updateSetting('ui', 'defaultViewMode', 'list');
            const { settings } = useSettingsStore.getState();
            expect(settings.gallery.itemsPerPage).toBe(20);
        });

        it('updates numeric values', () => {
            const { updateSetting } = useSettingsStore.getState();
            updateSetting('gallery', 'itemsPerPage', 50);
            const { settings } = useSettingsStore.getState();
            expect(settings.gallery.itemsPerPage).toBe(50);
        });

        it('updates boolean values', () => {
            const { updateSetting } = useSettingsStore.getState();
            updateSetting('gallery', 'autoRefreshOnJobComplete', false);
            const { settings } = useSettingsStore.getState();
            expect(settings.gallery.autoRefreshOnJobComplete).toBe(false);
        });
    });

    describe('updateSettings', () => {
        it('updates multiple settings at once', () => {
            const { updateSettings } = useSettingsStore.getState();
            updateSettings({
                ui: { defaultViewMode: 'list', defaultGridColumns: 6 },
                gallery: { itemsPerPage: 40 }
            });
            const { settings } = useSettingsStore.getState();
            expect(settings.ui.defaultViewMode).toBe('list');
            expect(settings.ui.defaultGridColumns).toBe(6);
            expect(settings.gallery.itemsPerPage).toBe(40);
        });

        it('merges with existing settings (does not replace category)', () => {
            const { updateSettings } = useSettingsStore.getState();
            updateSettings({ ui: { defaultViewMode: 'list' } });
            const { settings } = useSettingsStore.getState();
            // Other ui settings should still be there
            expect(settings.ui.defaultGridColumns).toBe(4);
            expect(settings.ui.toastSuccessDuration).toBe(3000);
        });

        it('ignores unknown categories', () => {
            const { updateSettings } = useSettingsStore.getState();
            // Should not throw when category doesn't exist
            expect(() => updateSettings({ unknownCategory: { value: 1 } })).not.toThrow();
        });
    });

    describe('resetSettings', () => {
        it('resets all settings to defaults', () => {
            const { updateSetting, resetSettings } = useSettingsStore.getState();
            updateSetting('ui', 'defaultViewMode', 'list');
            updateSetting('gallery', 'itemsPerPage', 100);
            resetSettings();
            const { settings } = useSettingsStore.getState();
            expect(settings.ui.defaultViewMode).toBe('grid');
            expect(settings.gallery.itemsPerPage).toBe(20);
        });
    });

    describe('resetCategory', () => {
        it('resets only the specified category', () => {
            const { updateSetting, resetCategory } = useSettingsStore.getState();
            updateSetting('ui', 'defaultViewMode', 'list');
            updateSetting('gallery', 'itemsPerPage', 100);
            resetCategory('ui');
            const { settings } = useSettingsStore.getState();
            expect(settings.ui.defaultViewMode).toBe('grid'); // Reset
            expect(settings.gallery.itemsPerPage).toBe(100); // Unchanged
        });
    });

    describe('getSetting', () => {
        it('returns the current value for a setting', () => {
            const { getSetting } = useSettingsStore.getState();
            expect(getSetting('ui', 'defaultViewMode')).toBe('grid');
        });

        it('returns undefined for unknown key', () => {
            const { getSetting } = useSettingsStore.getState();
            expect(getSetting('ui', 'unknownKey')).toBeUndefined();
        });

        it('returns updated value after change', () => {
            const { updateSetting, getSetting } = useSettingsStore.getState();
            updateSetting('ui', 'defaultViewMode', 'list');
            expect(getSetting('ui', 'defaultViewMode')).toBe('list');
        });
    });
});
