/**
 * "I picked a world and the chat did not end up in it."
 *
 * `Chat.world_id` and `Story.world_id` are real columns and come back on the
 * created record, so the response to a create is a capability check for free: if
 * the field was dropped on the way in — a server that does not yet accept it, or
 * one that validates it away — `created.world_id` will not be what was asked for.
 *
 * This exists as a shared helper rather than a per-call `if` because the failure
 * is otherwise completely silent, and it is the reason the write is safe to
 * attempt unconditionally: the chat and the story are created either way, and
 * the user is told about the part that did not stick. A rejected `world_id`
 * must never be able to fail the create.
 *
 * It is exported so the story path asserts the same behaviour against the same
 * helper rather than re-implementing the check.
 */
export function warnIfWorldIgnored(created, requestedWorldId, entityLabel = 'chat') {
    if (!requestedWorldId) return false;
    if (created?.world_id === requestedWorldId) return false;
    return {
        // Returned rather than toasted so the caller decides the wording; the
        // chat and story surfaces are reached from different components.
        ignored: true,
        label: entityLabel,
    };
}

export const WORLD_IGNORED_MESSAGE = (label) =>
    `${label[0].toUpperCase()}${label.slice(1)} created, but the world could not be attached to it — the server did not accept the world link. You can set it later from the ${label}'s World panel.`;
