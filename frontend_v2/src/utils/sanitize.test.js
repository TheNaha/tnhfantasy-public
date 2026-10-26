import { describe, it, expect } from 'vitest';
import { sanitizeHtml, SAFE_TAGS, SAFE_ATTR } from './sanitize';

describe('sanitizeHtml Utility', () => {
    it('returns empty string for null, undefined, or non-string inputs', () => {
        expect(sanitizeHtml(null)).toBe('');
        expect(sanitizeHtml(undefined)).toBe('');
        expect(sanitizeHtml(123)).toBe('');
        expect(sanitizeHtml({})).toBe('');
    });

    it('strips dangerous script tags and event handlers', () => {
        const malicious = '<p>Hello</p><script>alert("xss")</script><img src="x" onerror="alert(1)">';
        const cleaned = sanitizeHtml(malicious);
        expect(cleaned).not.toContain('<script');
        expect(cleaned).not.toContain('onerror');
        expect(cleaned).toContain('<p>Hello</p>');
    });

    it('preserves safe formatting tags and fantasy ruby typography', () => {
        const input = '<p>Character name: <ruby>夜空<rp>(</rp><rt>よぞら</rt><rp>)</rp></ruby> with <mark>spoiler</mark></p>';
        const cleaned = sanitizeHtml(input);
        expect(cleaned).toContain('<ruby>夜空<rp>(</rp><rt>よぞら</rt><rp>)</rp></ruby>');
        expect(cleaned).toContain('<mark>spoiler</mark>');
    });

    it('ensures anchor links receive target="_blank" and rel="noopener noreferrer"', () => {
        const input = '<a href="https://civitai.com/models/1234">Civitai Model</a>';
        const cleaned = sanitizeHtml(input);
        expect(cleaned).toContain('href="https://civitai.com/models/1234"');
        expect(cleaned).toContain('target="_blank"');
        expect(cleaned).toContain('rel="noopener noreferrer"');
    });

    it('exports standard SAFE_TAGS and SAFE_ATTR arrays', () => {
        expect(SAFE_TAGS).toContain('ruby');
        expect(SAFE_TAGS).toContain('rt');
        expect(SAFE_TAGS).toContain('mark');
        expect(SAFE_ATTR).toContain('href');
    });
});
