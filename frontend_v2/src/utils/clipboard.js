/**
 * Securely copies text to clipboard, preventing errors in non-secure contexts (HTTP)
 * where navigator.clipboard might be undefined.
 */
export async function copyToClipboard(text) {
    // Try Modern Async API first (if available and secure)
    if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (err) {
            console.warn("Clipboard API failed, falling back to legacy:", err);
        }
    }

    // Fallback: TextArea hack for HTTP or older browsers
    //
    // This is the path every insecure origin takes — `navigator.clipboard` is
    // undefined there, so the block above is skipped entirely and this is the
    // only attempt.
    let textArea = null;
    try {
        textArea = document.createElement("textarea");
        textArea.value = text;

        // Ensure it's not visible but part of DOM
        textArea.style.position = "fixed";
        textArea.style.left = "-9999px";
        textArea.style.top = "0";
        document.body.appendChild(textArea);

        textArea.focus();
        textArea.select();

        return document.execCommand('copy');
    } catch (err) {
        console.error("Fallback copy failed:", err);
        return false;
    } finally {
        // Removed in `finally`, not after the call. `document.execCommand` is
        // `undefined` in jsdom and removed from several browsers, so the
        // `removeChild` on the success path never ran whenever it threw — and a
        // copy attempt is the first thing a user does after a story is
        // published, so these accumulated in the live DOM as invisible,
        // focusable textareas over the page.
        if (textArea?.parentNode) textArea.parentNode.removeChild(textArea);
    }
}
