import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Flame, Loader2, TrendingUp } from 'lucide-react';
import { trendingAPI, itemsAPI } from '../services/api';
import EmptyState from '../components/EmptyState';

const VIDEO_PLACEHOLDER = 'https://static.prod-images.emergentagent.com/jobs/7ecda9fa-840f-42b6-a697-5367aaabdf99/images/54cc39fbc674b1e47eb9c19e535e10a091317d4c51804e073bbaf99dac7b9666.png';

const PLATFORM_COLORS = {
  instagram: 'bg-gradient-to-br from-purple-500 to-pink-500',
  youtube:   'bg-red-600',
  facebook:  'bg-blue-600',
};
const PLATFORM_LABELS = {
  instagram: 'Instagram',
  youtube:   'YouTube',
  facebook:  'Facebook',
};

const PERIODS = [
  { value: 'day',  label: '24h' },
  { value: 'week', label: 'This Week' },
  { value: 'all',  label: 'All Time' },
];

export default function TrendingPage() {
  const navigate   = useNavigate();
  const [items, setItems]         = useState([]);
  const [loading, setLoading]     = useState(true);
  const [categories, setCategories] = useState([]);
  const [period, setPeriod]       = useState('week');
  const [category, setCategory]   = useState('');
  const [page, setPage]           = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [savingId, setSavingId]   = useState(null); // item being saved to library
  const [saveMsg, setSaveMsg]     = useState(null);

  const fetchTrending = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await trendingAPI.list({
        period,
        category: category || undefined,
        page,
        limit: 20,
      });
      setItems(data.items || []);
      setTotalPages(data.pages || 1);

      // Collect unique categories for filter tabs
      const cats = [...new Set((data.items || []).map(i => i.category).filter(Boolean))];
      if (cats.length) setCategories(cats);
    } catch (err) {
      console.error('Trending fetch failed:', err);
    } finally {
      setLoading(false);
    }
  }, [period, category, page]);

  useEffect(() => { fetchTrending(); }, [fetchTrending]);

  const handleSaveToLibrary = async (item) => {
    setSavingId(item.id);
    setSaveMsg(null);
    try {
      await itemsAPI.save(item.url);
      setSaveMsg({ type: 'success', text: `Saved "${item.title || 'item'}" to your library!` });
      setTimeout(() => setSaveMsg(null), 4000);
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (detail?.type === 'duplicate') {
        setSaveMsg({ type: 'info', text: 'Already in your library.' });
      } else {
        setSaveMsg({ type: 'error', text: 'Could not save. Please try again.' });
      }
      setTimeout(() => setSaveMsg(null), 4000);
    } finally {
      setSavingId(null);
    }
  };

  return (
    <div data-testid="trending-page">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-2xl bg-orange-100 flex items-center justify-center">
          <TrendingUp className="w-5 h-5 text-orange-500" />
        </div>
        <div>
          <h1 className="font-heading text-2xl font-semibold text-text-primary">Trending</h1>
          <p className="text-sm text-text-secondary">Most-hyped content across all users</p>
        </div>
      </div>

      {/* Save message */}
      <AnimatePresence>
        {saveMsg && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className={`mb-4 px-4 py-2.5 rounded-xl text-sm font-medium text-center border
              ${saveMsg.type === 'success' ? 'bg-green-50 text-green-700 border-green-200' :
                saveMsg.type === 'error'   ? 'bg-red-50 text-red-700 border-red-200' :
                                             'bg-blue-50 text-blue-700 border-blue-200'}`}
          >
            {saveMsg.text}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        {/* Period tabs */}
        <div className="flex items-center gap-1 bg-surface-hover rounded-full p-1">
          {PERIODS.map(p => (
            <button
              key={p.value}
              onClick={() => { setPeriod(p.value); setPage(1); }}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-all
                ${period === p.value
                  ? 'bg-white text-text-primary shadow-sm'
                  : 'text-text-secondary hover:text-text-primary'}`}
            >
              {p.label}
            </button>
          ))}
        </div>

        {/* Category filter */}
        {categories.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              onClick={() => { setCategory(''); setPage(1); }}
              className={`px-3 py-1 rounded-full text-xs font-medium border transition-all
                ${!category ? 'bg-brand/10 border-brand/20 text-brand' : 'border-border-default text-text-secondary hover:border-brand/30'}`}
            >
              All
            </button>
            {categories.slice(0, 8).map(cat => (
              <button
                key={cat}
                onClick={() => { setCategory(cat); setPage(1); }}
                className={`px-3 py-1 rounded-full text-xs font-medium border transition-all
                  ${category === cat ? 'bg-brand/10 border-brand/20 text-brand' : 'border-border-default text-text-secondary hover:border-brand/30'}`}
              >
                {cat}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Grid */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 text-brand animate-spin" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title="Nothing trending yet"
          message="Be the first! Hype a saved reel to add it to the trending feed."
        />
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 md:gap-6">
            {items.map((item, i) => (
              <motion.div
                key={item.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: i * 0.04 }}
                className="bg-white border border-border-default rounded-2xl shadow-sm overflow-hidden group"
                data-testid={`trending-card-${item.id}`}
              >
                {/* Thumbnail — clicking opens source URL */}
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block relative aspect-[9/16] bg-surface-hover overflow-hidden"
                  onClick={e => e.stopPropagation()}
                >
                  <img
                    src={item.thumbnail_url || VIDEO_PLACEHOLDER}
                    alt={item.title}
                    className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
                    onError={e => { e.target.src = VIDEO_PLACEHOLDER; }}
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent" />

                  {/* Platform badge */}
                  {item.platform && (
                    <div className="absolute top-3 left-3">
                      <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[10px] uppercase tracking-wider font-semibold text-white ${PLATFORM_COLORS[item.platform] || 'bg-text-secondary'}`}>
                        {PLATFORM_LABELS[item.platform] || item.platform}
                      </span>
                    </div>
                  )}

                  {/* Hype count badge */}
                  <div className="absolute top-3 right-3 flex items-center gap-1 px-2 py-1 rounded-full bg-orange-500/90 backdrop-blur-sm text-white text-[11px] font-bold">
                    <Flame className="w-3 h-3 fill-white" />
                    {item.hype_count}
                  </div>

                  {/* Bottom info */}
                  <div className="absolute bottom-0 left-0 right-0 p-3">
                    <h3 className="text-white text-sm font-semibold line-clamp-2 leading-snug">
                      {item.title || 'Untitled'}
                    </h3>
                    {item.category && (
                      <span className="inline-block mt-1.5 px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider font-medium bg-white/20 text-white/90 backdrop-blur-sm">
                        {item.category}
                      </span>
                    )}
                  </div>
                </a>

                {/* Save to Library button */}
                <div className="px-3 py-2.5">
                  <button
                    onClick={() => handleSaveToLibrary(item)}
                    disabled={savingId === item.id}
                    className="w-full py-1.5 rounded-full text-xs font-semibold border border-brand/30 text-brand bg-brand/5 hover:bg-brand/10 transition-colors disabled:opacity-50"
                  >
                    {savingId === item.id ? (
                      <span className="flex items-center justify-center gap-1.5">
                        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Saving…
                      </span>
                    ) : 'Save to Library'}
                  </button>
                </div>
              </motion.div>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-3 mt-10">
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
