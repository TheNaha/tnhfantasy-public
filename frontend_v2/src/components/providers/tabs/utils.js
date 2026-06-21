export const STATUS_TONE = {
    running: 'green', active: 'green', connected: 'green',
    stopped: 'gray', idle: 'gray',
    queued: 'blue', reconciling: 'blue', completed: 'green',
    deploying: 'purple', failed: 'red',
};

export function statusDotClass(status) {
    const map = {
        green: 'text-green-400', running: 'text-green-400', active: 'text-green-400',
        blue: 'text-blue-400', queued: 'text-blue-400', reconciling: 'text-blue-400',
        purple: 'text-purple-400', deploying: 'text-purple-400',
        red: 'text-red-400', failed: 'text-red-400',
        yellow: 'text-yellow-400', orange: 'text-orange-400',
        gray: 'text-gray-500', stopped: 'text-gray-500', idle: 'text-gray-500',
    };
    return map[status] || map.gray;
}

export function humanize(status) {
    if (!status) return 'Unknown';
    return status.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function capitalize(v) {
    return v ? v.charAt(0).toUpperCase() + v.slice(1) : v;
}
