import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { itemsAPI, categoriesAPI, formatApiErrorDetail } from '../services/api';
import SaveUrlInput from '../components/SaveUrlInput';
import ItemCard from '../components/ItemCard';
import EmptyState from '../components/EmptyState';
import { Filter, Loader2 } from 'lucide-react';

export default function HomePage() {
  const [items, setItems] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState(null);
  const [filter, setFilter] = useState({ category: '', platform: '', status: '' });
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  const fetchItems = useCallback(async () => {
    try {
      const params = { page, limit: 20 };
      if (filter.category) params.category = filter.category;
      if (filter.platform) params.platform = filter.platform;
      if (filter.status) params.status = filter.status;
      const { data } = await itemsAPI.list(params);
      setItems(data.items || []);
      setTotalPages(data.pages || 1);
    } catch (err) {
      console.error('Failed to fetch items:', err);
    } finally {
      setLoading(false);
    }
  }, [page, filter]);

  const fetchCategories = useCallback(async () => {
    try {
      const { data } = await categoriesAPI.list();
      setCategories(data.categories || []);
    } catch {}
  }, []);

  useEffect(() => { fetchItems(); }, [fetchItems]);
  useEffect(() => { fetchCategories(); }, [fetchCategories]);

  const handleSave = async (url) => {
    setSaving(true);
    setSaveMsg({ type: 'info', text: '⏳ Checking content availability…' });
    try {
      const { data } = await itemsAPI.save(url);
      if (data.status === 'duplicate') {
        setSaveMsg({ type: 'info', text: 'This URL was already saved.' });
      } else {
        setSaveMsg({ type: 'success', text: '✓ Saved! Analysing content — this takes ~15 seconds.' });
        setTimeout(fetchItems, 400);
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      // Friendly message for pre-check failures (content removed / private)
      const text = (detail && typeof detail === 'object' && detail.type === 'unavailable')
        ? `Content unavailable: ${detail.reason || 'This video has been removed or is no longer accessible.'}`
        : (formatApiErrorDetail(detail) || 'Failed to save');
      setSaveMsg({ type: 'error', text });
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(null), 4000);
    }
  };

  // Poll every 2s while any item is still processing
  useEffect(() => {
    const hasProcessing = items.some(i => i.source_status === 'processing');
    if (!hasProcessing) return;
    const interval = setInterval(fetchItems, 2000);
    return () => clearInterval(interval);
  }, [items, fetchItems]);

  return (
    <div data-testid="home-page">
      {/* Save Input */}
      <SaveUrlInput onSave={handleSave} loading={saving} />

      {/* Save Message */}
      {saveMsg && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          className={`max-w-3xl mx-auto mb-6 px-4 py-3 rounded-xl text-sm font-medium text-center ${
            saveMsg.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' :
            saveMsg.type === 'error' ? 'bg-red-50 text-red-700 border border-red-200' :
            'bg-blue-50 text-blue-700 border border-blue-200'
          }`}
          data-testid="save-message"
        >
          {saveMsg.text}
        </motion.div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-6" data-testid="filters">
        <Filter className="w-4 h-4 text-text-secondary" />
        <select
          value={filter.platform}
          onChange={(e) => { setFilter(f => ({ ...f, platform: e.target.value })); setPage(1); }}
          data-testid="filter-platform"
          className="px-3 py-1.5 rounded-full text-xs border border-border-default bg-white text-text-secondary focus:border-brand outline-none"
        >
          <option value="">All Platforms</option>
          <option value="instagram">Instagram</option>
          <option value="youtube">YouTube</option>
          <option value="facebook">Facebook</option>
        </select>
        <select
          value={filter.category}
          onChange={(e) => { setFilter(f => ({ ...f, category: e.target.value })); setPage(1); }}
          data-testid="filter-category"
          className="px-3 py-1.5 rounded-full text-xs border border-border-default bg-white text-text-secondary focus:border-brand outline-none"
        >
          <option value="">All Categories</option>
          {categories.map(c => (
            <option key={c.name} value={c.name}>{c.name} ({c.count})</option>
          ))}
        </select>
        <select
          value={filter.status}
          onChange={(e) => { setFilter(f => ({ ...f, status: e.target.value })); setPage(1); }}
          data-testid="filter-status"
          className="px-3 py-1.5 rounded-full text-xs border border-border-default bg-white text-text-secondary focus:border-brand outline-none"
        >
          <option value="">All Status</option>
          <option value="processing">Processing</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
        </select>
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 text-brand animate-spin" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title="Your library is empty"
          message="Paste a Reel or Short URL above to start saving content you love."
        />
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 md:gap-6" data-testid="items-grid">
            {items.map((item, i) => (
              <ItemCard key={item.id} item={item} index={i} />
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-3 mt-10" data-testid="pagination">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-4 py-2 rounded-full text-sm border border-border-default bg-white hover:bg-surface-hover disabled:opacity-40 transition-colors"
              >
                Previous
              </button>
              <span className="text-sm text-text-secondary">Page {page} of {totalPages}</span>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-4 py-2 rounded-full text-sm border border-border-default bg-white hover:bg-surface-hover disabled:opacity-40 transition-colors"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
