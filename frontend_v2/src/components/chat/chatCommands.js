export const COMMANDS = [
    { cmd: '/silent', desc: 'Send silently without triggering AI reply', icon: '🤫', argPlaceholder: 'Message text...' },
    { cmd: '/story', desc: 'Insert a narrative event', icon: '📖', argPlaceholder: 'Story text...' },
    { cmd: '/puppet', desc: 'Speak as the character', icon: '🎭', argPlaceholder: 'Character speech...' },
    { cmd: '/time', desc: 'Update story time', icon: '⏰', argPlaceholder: 'e.g. Midnight, +2 hours...' },
    { cmd: '/location', desc: 'Update story location', icon: '📍', argPlaceholder: 'e.g. The Library...' },
    { cmd: '/action', desc: 'Perform an action', icon: '🏃', argPlaceholder: 'Action description...' },
    { cmd: '/suggest', desc: 'Auto-fill a suggested response', icon: '🪄', noArgs: true }
];
