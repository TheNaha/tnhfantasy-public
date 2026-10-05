import { useId } from 'react';

/**
 * Label + control, associated.
 *
 * The `<label>` used to be a bare *sibling* of the input: no `htmlFor`, no
 * matching `id`. Clicking it focused nothing, and every control this component
 * renders was announced to assistive tech as an unnamed text field — with a
 * visible label right above it, which is the worst combination: it looks
 * labelled to a sighted user and is not labelled to anyone else.
 *
 * `useId()` makes the pair unique per instance, so the same component used
 * twice on a page (character forms, lorebook forms) cannot produce duplicate
 * `id`s, and every existing call site is fixed by this one change rather than
 * by editing each of them.
 */
function FormInput({ label, value, onChange, type = 'text', placeholder, required }) {
    const fieldId = useId();
    return (
        <div className="mb-4">
            <label htmlFor={fieldId} className="block text-sm font-medium text-gray-300 mb-1">{label}{required && '*'}</label>
            {type === 'textarea' ? (
                <textarea
                    id={fieldId}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                    value={value || ''}
                    onChange={onChange}
                    placeholder={placeholder}
                    rows={3}
                />
            ) : (
                <input
                    id={fieldId}
                    type={type}
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    value={value || ''}
                    onChange={onChange}
                    placeholder={placeholder}
                />
            )}
        </div>
    );
}

export default FormInput;
