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
    try {
        const textArea = document.createElement("textarea");
        textArea.value = text;
        
        // Ensure it's not visible but part of DOM
        textArea.style.position = "fixed";
        textArea.style.left = "-9999px";
        textArea.style.top = "0";
        document.body.appendChild(textArea);
        
        textArea.focus();
        textArea.select();
        
        const successful = document.execCommand('copy');
        document.body.removeChild(textArea);
        return successful;
    } catch (err) {
        console.error("Fallback copy failed:", err);
        return false;
    }
}
