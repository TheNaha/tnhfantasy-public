function FormInput({ label, value, onChange, type = 'text', placeholder, required }) {
    return (
        <div className="mb-4">
            <label className="block text-sm font-medium text-gray-300 mb-1">{label}{required && '*'}</label>
            {type === 'textarea' ? (
                <textarea
                    className="w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                    value={value || ''}
                    onChange={onChange}
                    placeholder={placeholder}
                    rows={3}
                />
            ) : (
                <input
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
