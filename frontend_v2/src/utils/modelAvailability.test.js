import { describe, expect, it } from 'vitest';
import {
    availabilityTone,
    formatAvailabilityBadgeLabel,
    getModelAvailabilitySummary,
    isProviderOnline,
    normalizeModelStatus,
} from './modelAvailability';

describe('modelAvailability utilities', () => {
    it('normalizes string and object model statuses', () => {
        expect(normalizeModelStatus('READY')).toBe('ready');
        expect(normalizeModelStatus({ status: 'Downloading' })).toBe('downloading');
        expect(normalizeModelStatus(null)).toBe('unknown');
    });

    it('detects online providers from runtime state', () => {
        expect(isProviderOnline({ id: 'modal-step', runtime_state: { status: 'running' } })).toBe(true);
        expect(isProviderOnline({ id: 'modal-step', runtime_state: { status: 'stopped' } })).toBe(false);
        expect(isProviderOnline({ id: 'modal-step', enabled: false, runtime_state: { status: 'running' } })).toBe(false);
    });

    it('returns available when all online providers report ready', () => {
        const summary = getModelAvailabilitySummary(
            {
                'modal-step': 'ready',
                'modal-zetsuke': 'installed',
            },
            [
                { id: 'modal-step', runtime_state: { status: 'running' } },
                { id: 'modal-zetsuke', runtime_state: { status: 'running' } },
            ]
        );

        expect(summary.label).toBe('Available');
        expect(summary.availableCount).toBe(2);
        expect(summary.scopeCount).toBe(2);
    });

    it('returns partial when only some online providers are ready', () => {
        const summary = getModelAvailabilitySummary(
            {
                'modal-step': 'ready',
                'modal-zetsuke': 'failed',
            },
            [
                { id: 'modal-step', runtime_state: { status: 'running' } },
                { id: 'modal-zetsuke', runtime_state: { status: 'running' } },
            ]
        );

        expect(summary.label).toBe('Partial');
        expect(summary.availableCount).toBe(1);
        expect(summary.scopeCount).toBe(2);
    });

    it('returns no providers online when runtime data exists but nothing is online', () => {
        const summary = getModelAvailabilitySummary(
            {
                'modal-step': 'ready',
            },
            [
                { id: 'modal-step', runtime_state: { status: 'stopped' } },
            ]
        );

        expect(summary.label).toBe('No providers online');
    });

    it('falls back to provider statuses when runtime provider list is unavailable', () => {
        const summary = getModelAvailabilitySummary({
            'modal-step': 'ready',
            'modal-zetsuke': 'failed',
        });

        expect(summary.label).toBe('Partial');
        expect(summary.availableCount).toBe(1);
        expect(summary.scopeCount).toBe(2);
    });

    it('formats badge labels and tone classes for compact card rendering', () => {
        expect(formatAvailabilityBadgeLabel('Loading providers')).toBe('Loading');
        expect(formatAvailabilityBadgeLabel('No providers online')).toBe('Offline');
        expect(availabilityTone('Available')).toContain('text-green-300');
        expect(availabilityTone('Partial')).toContain('text-yellow-300');
    });
});