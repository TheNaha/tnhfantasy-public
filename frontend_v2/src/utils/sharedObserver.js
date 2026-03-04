/**
 * Shared IntersectionObserver instances for lazy loading.
 * This prevents creating hundreds of individual observers when rendering
 * large grids of images (like in the gallery view).
 */
const observers = new Map();
const elementData = new WeakMap(); // maps element -> { callback, observer }

/**
 * Initializes the shared observer if it hasn't been created yet for the given options.
 */
function getObserver(rootMargin = '200px', threshold = 0) {
    if (typeof IntersectionObserver === 'undefined') return null;

    const key = `${rootMargin}_${threshold}`;
    if (!observers.has(key)) {
        const observer = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        const data = elementData.get(entry.target);
                        if (data && data.callback) {
                            data.callback();
                            // Once intersecting, we can stop observing
                            if (data.observer) {
                                data.observer.unobserve(entry.target);
                            }
                            elementData.delete(entry.target);
                        }
                    }
                });
            },
            { rootMargin, threshold }
        );
        observers.set(key, observer);
    }
    return observers.get(key);
}

/**
 * Registers an element to be observed for intersection.
 *
 * @param {Element} element The DOM element to observe.
 * @param {Function} callback The function to call when the element intersects.
 * @param {Object} options Options for the observer (rootMargin, threshold).
 */
export function observeIntersection(element, callback, options = {}) {
    if (!element) return;

    const { rootMargin = '200px', threshold = 0 } = options;
    const obs = getObserver(rootMargin, threshold);

    elementData.set(element, { callback, observer: obs });
    if (obs) {
        obs.observe(element);
    } else {
        // Fallback if IntersectionObserver is not supported
        callback();
    }
}

/**
 * Unregisters an element from the shared observer.
 *
 * @param {Element} element The DOM element to stop observing.
 */
export function unobserveIntersection(element) {
    if (!element) return;

    const data = elementData.get(element);
    if (data) {
        if (data.observer) {
            data.observer.unobserve(element);
        }
        elementData.delete(element);
    }
}
