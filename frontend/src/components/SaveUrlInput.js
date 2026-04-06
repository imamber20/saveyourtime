import React, { useState } from 'react';
import { Link, Plus } from 'lucide-react';
import { motion } from 'framer-motion';

export default function SaveUrlInput({ onSave, loading }) {
  const [url, setUrl] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (url.trim()) {
      onSave(url.trim());
      setUrl('');
    }
  };

  return (
    <motion.form
      onSubmit={handleSubmit}
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="relative max-w-3xl mx-auto mb-10"
      data-testid="save-url-form"
    >
      <div className="relative">
        <div className="absolute left-6 top-1/2 -translate-y-1/2 text-text-secondary pointer-events-none">
          <Link className="w-5 h-5" />
        </div>
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="Paste a Reel or Short URL to save..."
          data-testid="save-url-input"
          className="w-full text-base sm:text-lg pl-14 pr-16 py-4 sm:py-5 bg-white border border-border-default rounded-full shadow-[0_8px_30px_rgba(0,0,0,0.04)] focus:border-brand focus:shadow-[0_8px_30px_rgba(195,107,88,0.1)] outline-none transition-all duration-300 font-body"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !url.trim()}
          data-testid="save-url-button"
          className="absolute right-2.5 top-1/2 -translate-y-1/2 bg-brand text-page p-3 rounded-full hover:bg-brand-hover transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed shadow-[0_2px_10px_rgba(195,107,88,0.2)]"
          aria-label="Save URL"
        >
          {loading ? (
            <div className="w-5 h-5 border-2 border-page border-t-transparent rounded-full animate-spin" />
          ) : (
            <Plus className="w-5 h-5" />
          )}
        </button>
      </div>
    </motion.form>
  );
}
