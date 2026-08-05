/**
 * Tests for tavernUtils.js
 */

import { describe, it, expect, vi, beforeAll } from 'vitest';
import { substituteTemplateVars, parseTavernMessage, substituteCharacterTemplates } from './tavernUtils';

// Mock Date for deterministic time/date tests
const FIXED_DATE = new Date('2024-06-15T14:30:00Z');

describe('substituteTemplateVars', () => {
    beforeAll(() => {
        vi.useFakeTimers();
        vi.setSystemTime(FIXED_DATE);
    });

    it('substitutes {{user}} with provided user value', () => {
        expect(substituteTemplateVars('Hello {{user}}!', { user: 'Naufal' })).toBe('Hello Naufal!');
    });

    it('substitutes {{char}} with provided char value', () => {
        expect(substituteTemplateVars('I am {{char}}.', { char: 'Luna' })).toBe('I am Luna.');
    });

    it('defaults {{user}} to "User" when not provided', () => {
        expect(substituteTemplateVars('Hello {{user}}!')).toBe('Hello User!');
    });

    it('substitutes both {{user}} and {{char}} in same string', () => {
        const result = substituteTemplateVars(
            '{{user}} meets {{char}} in the forest.',
            { user: 'Alex', char: 'Lyra' }
        );
        expect(result).toBe('Alex meets Lyra in the forest.');
    });

    it('handles case-insensitive variable names', () => {
        expect(substituteTemplateVars('{{USER}} and {{CHAR}}', { user: 'Bob', char: 'Aria' }))
            .toBe('Bob and Aria');
    });

    it('substitutes {{date}} with ISO date', () => {
        const result = substituteTemplateVars('Today is {{date}}.');
        expect(result).toBe('Today is 2024-06-15.');
    });

    it('handles {{random::}} with single option', () => {
        expect(substituteTemplateVars('{{random::only}}')).toBe('only');
    });

    it('handles {{random::}} with multiple options', () => {
        const result = substituteTemplateVars('{{random::a::b::c}}');
        expect(['a', 'b', 'c']).toContain(result);
    });

    it('handles {{roll::NdX}} dice roll', () => {
        const result = substituteTemplateVars('{{roll::1d6}}');
        const num = parseInt(result, 10);
        expect(num).toBeGreaterThanOrEqual(1);
        expect(num).toBeLessThanOrEqual(6);
    });

    it('handles {{roll::2d6}} dice roll', () => {
        const result = substituteTemplateVars('{{roll::2d6}}');
        const num = parseInt(result, 10);
        expect(num).toBeGreaterThanOrEqual(2);
        expect(num).toBeLessThanOrEqual(12);
    });

    it('leaves unknown variables as-is', () => {
        expect(substituteTemplateVars('{{unknown_var}}')).toBe('{{unknown_var}}');
    });

    it('returns empty string for empty input', () => {
        expect(substituteTemplateVars('')).toBe('');
    });

    it('returns text unchanged when no variables present', () => {
        expect(substituteTemplateVars('hello world')).toBe('hello world');
    });

    it('handles null/undefined gracefully', () => {
        expect(substituteTemplateVars(null)).toBe('');
        expect(substituteTemplateVars(undefined)).toBe('');
    });
});


describe('parseTavernMessage', () => {
    it('parses pure action text', () => {
        const result = parseTavernMessage('*Luna smiles warmly*');
        expect(result).toHaveLength(1);
        expect(result[0]).toEqual({ type: 'action', content: 'Luna smiles warmly' });
    });

    it('parses pure speech text', () => {
        const result = parseTavernMessage('"Hello there, adventurer!"');
        expect(result).toHaveLength(1);
        expect(result[0]).toEqual({ type: 'speech', content: 'Hello there, adventurer!' });
    });

    it('parses pure prose text', () => {
        const result = parseTavernMessage('The wind howled through the trees.');
        expect(result).toHaveLength(1);
        expect(result[0]).toEqual({ type: 'prose', content: 'The wind howled through the trees.' });
    });

    it('parses mixed action + speech', () => {
        const result = parseTavernMessage('*Luna steps forward* "Welcome to my realm."');
        expect(result).toHaveLength(2);
        expect(result[0]).toEqual({ type: 'action', content: 'Luna steps forward' });
        expect(result[1]).toEqual({ type: 'speech', content: 'Welcome to my realm.' });
    });

    it('parses complex mixed message', () => {
        const text = '*She smiles* "I\'ve been waiting for you." The air crackles with magic. *Her eyes glow*';
        const result = parseTavernMessage(text);
        expect(result.length).toBeGreaterThanOrEqual(3);
        expect(result[0].type).toBe('action');
        expect(result[1].type).toBe('speech');
    });

    it('returns prose segment for empty input', () => {
        const result = parseTavernMessage('');
        expect(result).toEqual([]);
    });

    it('handles null gracefully', () => {
        expect(parseTavernMessage(null)).toEqual([]);
    });

    it('handles text without any special markers', () => {
        const result = parseTavernMessage('Just plain text here.');
        expect(result).toHaveLength(1);
        expect(result[0].type).toBe('prose');
    });
});


describe('substituteCharacterTemplates', () => {
    it('substitutes {{char}} in description', () => {
        const char = { name: 'Luna', description: '{{char}} is a mage.' };
        const result = substituteCharacterTemplates(char);
        expect(result.description).toBe('Luna is a mage.');
    });

    it('substitutes {{user}} in first_mes', () => {
        const char = { name: 'Luna', first_mes: 'Hello {{user}}, I am {{char}}.' };
        const result = substituteCharacterTemplates(char, { user: 'Alex' });
        expect(result.first_mes).toBe('Hello Alex, I am Luna.');
    });

    it('handles null character gracefully', () => {
        expect(substituteCharacterTemplates(null)).toBeNull();
    });

    it('preserves non-template fields unchanged', () => {
        const char = { name: 'Luna', id: 'abc123', description: 'A mage.' };
        const result = substituteCharacterTemplates(char);
        expect(result.id).toBe('abc123');
        expect(result.name).toBe('Luna');
    });
});
