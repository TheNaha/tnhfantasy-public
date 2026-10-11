/**
 * The one constant the story-beat UI and the backend must agree on.
 *
 * `world_integration_service.TTS_BEAT_ROLE` is what narration writes onto a
 * beat; the panel keys on it to render the audio icon. A typo on either side
 * made the icon never appear, which is the kind of split these tests exist to
 * pin. Mirrored here because a test should not import the backend.
 */
export const TTS_BEAT_ROLE = 'tts';
