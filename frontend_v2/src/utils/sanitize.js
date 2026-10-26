/**
 * sanitize.js - Centralized HTML Sanitization for Rich Descriptions & Character Lore
 *
 * Uses DOMPurify to guard against XSS, template injection, and prototype pollution.
 * Standardizes security attributes on external links (target="_blank", rel="noopener noreferrer")
 * and enables safe fantasy typography including Japanese Furigana (<ruby>, <rt>, <rp>) and spoilers (<mark>).
 */
import DOMPurify from 'dompurify';

// Hook into DOMPurify to enforce secure external link attributes
if (typeof window !== 'undefined' && DOMPurify?.addHook) {
    try {
        DOMPurify.addHook('afterSanitizeAttributes', function (node) {
            if (node.tagName === 'A') {
                node.setAttribute('target', '_blank');
                node.setAttribute('rel', 'noopener noreferrer');
            }
        });
    } catch {
        // Safe no-op in non-browser or test runner mock environments
    }
}

/**
 * Standard allowlist of safe HTML tags for user/model descriptions.
 * Includes text layout, lists, code, and fantasy annotation tags (<ruby>, <rt>, <rp>, <mark>).
 */
export const SAFE_TAGS = [
    'p', 'br', 'b', 'i', 'em', 'strong', 'a', 'ul', 'ol', 'li', 'code',
    'pre', 'blockquote', 'span', 'div', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ruby', 'rt', 'rp', 'mark', 'small', 'sub', 'sup', 'table', 'thead', 'tbody', 'tr', 'th', 'td'
];

export const SAFE_ATTR = ['href', 'title', 'class', 'target', 'rel', 'style'];

/**
 * Sanitize an untrusted HTML string.
 *
 * @param {string} dirty - The input HTML string.
 * @param {object} [options={}] - Optional DOMPurify configuration overrides.
 * @returns {string} Sanitized, safe HTML string.
 */
export function sanitizeHtml(dirty, options = {}) {
    if (!dirty || typeof dirty !== 'string') {
        return '';
    }

    return DOMPurify.sanitize(dirty, {
        ALLOWED_TAGS: SAFE_TAGS,
        ALLOWED_ATTR: SAFE_ATTR,
        FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'input'],
        FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover'],
        ...options,
    });
}

export default sanitizeHtml;
