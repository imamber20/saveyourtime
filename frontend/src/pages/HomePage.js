import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { itemsAPI, categoriesAPI, formatApiErrorDetail } from '../services/api';
import SaveUrlInput from '../components/SaveUrlInput';
import ItemCard, { CheckingTile, ContentGoneTile } from '../components/ItemCard';
import EmptyState from '../components/EmptyState';
import { Filter, Loader2 } from 'lucide-react';

// Detect platform client-side so the checking tile shows the right badge immediately
const detectPlatformClient = (url) => {
  if (/instagram\.com\/(reel|reels|p)\//i.test(url)) return 'instagram';
  if (/youtube\.com\/(shorts|watch)|youtu\.be\//i.test(url)) return 'youtube';
  if (/facebook\.com\/(reel|.*videos)|fb\.watch/i.test(url)) return 'facebook';
  return null;
};

export default function HomePage() {
  const [items, setItems] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState(null);
  const [pendingTiles, setPendingTiles] = useState([]); // {id, platform, status:'checking'|'gone'}
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
    const tileId = Date.now();
    const platform = detectPlatformClient(url);
    // 1. Immediately show the checking skeleton tile
    setPendingTiles(t => [...t, { id: tileId, platform, status: 'checking' }]);
    setSaving(true);
    setSaveMsg(null);
    try {
      const { data } = await itemsAPI.save(url);
      // 2a. Success — remove checking tile, let fetchItems show the real card
      setPendingTiles(t => t.filter(x => x.id !== tileId));
      if (data.status === 'duplicate') {
        setSaveMsg({ type: 'info', text: 'This URL was already saved.' });
        setTimeout(() => setSaveMsg(null), 3000);
      } else {
        setTimeout(fetchItems, 300);
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      const isUnavailable = detail && typeof detail === 'object' && detail.type === 'unavailable';
      if (isUnavailable) {
        // 2b. Content gone — morph tile to 404 animation
        setPendingTiles(t => t.map(x => x.id === tileId ? { ...x, status: 'gone' } : x));
      } else {
        // 2c. Other error — remove tile, show brief message
        setPendingTiles(t => t.filter(x => x.id !== tileId));
        setSaveMsg({ type: 'error', text: formatApiErrorDetail(detail) || 'Failed to save. Please try again.' });
        setTimeout(() => setSaveMsg(null), 4000);
      }
    } finally {
      setSaving(false);
    }
  };

  const removePendingTile = (tileId) => {
    setPendingTiles(t => t.filter(x => x.id !== tileId));
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

      {/* Save Message (only for non-tile errors like duplicates) */}
      <AnimatePresence>
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
      </AnimatePresence>

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
      ) : items.length === 0 && pendingTiles.length === 0 ? (
        <EmptyState
          title="Your library is empty"
          message="Paste a Reel or Short URL above to start saving content you love."
        />
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 md:gap-6" data-testid="items-grid">
            {/* Pending tiles appear first — checking skeleton or 404 animation */}
            <AnimatePresence>
              {pendingTiles.map((tile, i) =>
                tile.status === 'checking' ? (
                  <CheckingTile key={tile.id} platform={tile.platform} index={i} />
                ) : (
                  <ContentGoneTile key={tile.id} platform={tile.platform} index={i}
                    onExpire={() => removePendingTile(tile.id)} />
                )
              )}
            </AnimatePresence>
            {items.map((item, i) => (
              <ItemCard key={item.id} item={item} index={i + pendingTiles.length} />
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
