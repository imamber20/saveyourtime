import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { collectionsAPI } from '../services/api';
import ItemCard from '../components/ItemCard';
import EmptyState from '../components/EmptyState';
import { ArrowLeft, Plus, X, Check, Loader2, AlertTriangle } from 'lucide-react';

const VIDEO_PLACEHOLDER = 'https://static.prod-images.emergentagent.com/jobs/7ecda9fa-840f-42b6-a697-5367aaabdf99/images/54cc39fbc674b1e47eb9c19e535e10a091317d4c51804e073bbaf99dac7b9666.png';

export default function CollectionDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [collection, setCollection] = useState(null);
  const [loading, setLoading] = useState(true);

  // Add Videos picker state
  const [showPicker, setShowPicker] = useState(false);
  const [availableItems, setAvailableItems] = useState([]);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [mismatchItems, setMismatchItems] = useState([]);
  const [showMismatchConfirm, setShowMismatchConfirm] = useState(false);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    fetchCollection();
  }, [id]);

  const fetchCollection = async () => {
    try {
      const { data } = await collectionsAPI.get(id);
      setCollection(data);
    } catch {
      navigate('/collections');
    } finally {
      setLoading(false);
    }
  };

  const openPicker = async () => {
    setShowPicker(true);
    setSelected(new Set());
    setPickerLoading(true);
    try {
      const { data } = await collectionsAPI.getAvailableItems(id);
      setAvailableItems(data.items || []);
    } catch (err) {
      console.error('Failed to load available items', err);
    } finally {
      setPickerLoading(false);
    }
  };

  const toggleSelect = (itemId) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  };

  const handleAddSelected = () => {
    if (selected.size === 0) return;
    // Check for category mismatches
    const collCategory = collection?.name;
    const mismatches = availableItems.filter(item =>
      selected.has(item.id) &&
      item.category &&
      collCategory &&
      !item.category.toLowerCase().includes(collCategory.toLowerCase()) &&
      !collCategory.toLowerCase().includes(item.category.toLowerCase())
    );
    if (mismatches.length > 0) {
      setMismatchItems(mismatches);
      setShowMismatchConfirm(true);
    } else {
      commitAdd();
    }
  };

  const commitAdd = async () => {
    setAdding(true);
    setShowMismatchConfirm(false);
    try {
      await Promise.all([...selected].map(itemId => collectionsAPI.addItem(id, itemId)));
      setShowPicker(false);
      setSelected(new Set());
      fetchCollection();
    } catch (err) {
      console.error('Failed to add items', err);
    } finally {
      setAdding(false);
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center py-20">
      <Loader2 className="w-8 h-8 text-brand animate-spin" />
    </div>
  );

  if (!collection) return null;

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} data-testid="collection-detail-page">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/collections')} data-testid="back-to-collections"
            className="p-2 rounded-full hover:bg-surface-hover transition-colors">
            <ArrowLeft className="w-4 h-4 text-text-secondary" />
          </button>
          <div>
            <h1 className="font-heading text-xl sm:text-2xl font-semibold text-text-primary">{collection.name}</h1>
            {collection.description && (
              <p className="text-sm text-text-secondary">{collection.description}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-text-secondary">{collection.item_count || 0} items</span>
          <button
            onClick={openPicker}
            data-testid="add-videos-button"
            className="flex items-center gap-2 bg-brand text-page rounded-full px-4 py-2 text-sm font-medium hover:bg-brand-hover transition-all shadow-[0_2px_10px_rgba(195,107,88,0.2)]"
          >
            <Plus className="w-4 h-4" /> Add Videos
          </button>
        </div>
      </div>

      {(!collection.items || collection.items.length === 0) ? (
        <EmptyState
          title="This collection is empty"
          message="Add videos from your library using the Add Videos button."
          actionLabel="Add Videos"
          onAction={openPicker}
        />
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 md:gap-6" data-testid="collection-items-grid">
          {collection.items.map((item, i) => (
            <ItemCard key={item.id} item={item} index={i} />
          ))}
        </div>
      )}

      {/* Add Videos Picker Modal */}
      <AnimatePresence>
        {showPicker && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/40 z-50 flex items-end sm:items-center justify-center p-4"
            onClick={(e) => { if (e.target === e.currentTarget) setShowPicker(false); }}
          >
            <motion.div
              initial={{ opacity: 0, y: 40 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 40 }}
              className="bg-white rounded-2xl w-full max-w-2xl max-h-[80vh] flex flex-col shadow-xl"
            >
              {/* Modal Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b border-border-default">
                <div>
                  <h2 className="font-heading font-semibold text-text-primary">Add Videos</h2>
                  <p className="text-xs text-text-secondary mt-0.5">
                    {selected.size > 0 ? `${selected.size} selected` : 'Select videos to add to this collection'}
                  </p>
                </div>
                <button onClick={() => setShowPicker(false)} className="p-1.5 rounded-lg hover:bg-surface-hover transition-colors">
                  <X className="w-4 h-4 text-text-secondary" />
                </button>
              </div>

              {/* Items list */}
              <div className="overflow-y-auto flex-1 p-4">
                {pickerLoading ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="w-6 h-6 text-brand animate-spin" />
                  </div>
                ) : availableItems.length === 0 ? (
                  <p className="text-center text-text-secondary py-12 text-sm">No items available to add.</p>
                ) : (
                  <div className="space-y-2">
                    {availableItems.map(item => {
                      const isSelected = selected.has(item.id);
                      const alreadyIn = item.in_collection;
                      return (
                        <button
                          key={item.id}
                          disabled={alreadyIn}
                          onClick={() => !alreadyIn && toggleSelect(item.id)}
                          className={`w-full flex items-center gap-3 p-3 rounded-xl border transition-all text-left ${
                            alreadyIn
                              ? 'opacity-40 cursor-not-allowed border-border-default'
                              : isSelected
                              ? 'border-brand bg-brand/5'
                              : 'border-border-default hover:border-sage hover:bg-surface-hover'
                          }`}
                        >
                          <div className="w-12 h-12 rounded-lg overflow-hidden flex-shrink-0 bg-surface-hover">
                            <img
                              src={item.thumbnail_url || VIDEO_PLACEHOLDER}
                              alt={item.title}
                              className="w-full h-full object-cover"
                              onError={(e) => { e.target.src = VIDEO_PLACEHOLDER; }}
                            />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-text-primary truncate">{item.title || 'Untitled'}</p>
                            <p className="text-xs text-text-secondary mt-0.5">
                              {item.category || item.platform}
                              {alreadyIn && ' · Already in collection'}
                            </p>
                          </div>
                          <div className={`w-5 h-5 rounded-full border-2 flex-shrink-0 flex items-center justify-center transition-all ${
                            isSelected ? 'bg-brand border-brand' : 'border-border-default'
                          }`}>
                            {isSelected && <Check className="w-3 h-3 text-white" />}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Footer */}
              <div className="px-6 py-4 border-t border-border-default flex justify-end gap-3">
                <button onClick={() => setShowPicker(false)}
                  className="border border-border-default rounded-full px-5 py-2 text-sm hover:bg-surface-hover transition-colors">
                  Cancel
                </button>
                <button
                  onClick={handleAddSelected}
                  disabled={selected.size === 0 || adding}
                  data-testid="confirm-add-videos"
                  className="bg-brand text-page rounded-full px-5 py-2 text-sm font-medium hover:bg-brand-hover transition-colors disabled:opacity-50"
                >
                  {adding ? 'Adding...' : `Add ${selected.size > 0 ? selected.size : ''} Video${selected.size !== 1 ? 's' : ''}`}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Category Mismatch Confirmation */}
      <AnimatePresence>
        {showMismatchConfirm && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.9, opacity: 0 }}
              className="bg-white rounded-2xl w-full max-w-sm p-6 shadow-xl"
            >
              <div className="flex items-center gap-3 mb-3">
                <div className="w-10 h-10 rounded-full bg-amber-50 flex items-center justify-center flex-shrink-0">
                  <AlertTriangle className="w-5 h-5 text-amber-500" />
                </div>
                <h3 className="font-heading font-semibold text-text-primary">Category mismatch</h3>
              </div>
              <p className="text-sm text-text-secondary mb-2">
                {mismatchItems.length} video{mismatchItems.length !== 1 ? 's' : ''} may not belong in <strong className="text-text-primary">{collection.name}</strong>:
              </p>
              <ul className="text-xs text-text-secondary space-y-1 mb-4 max-h-24 overflow-y-auto">
                {mismatchItems.map(item => (
                  <li key={item.id} className="truncate">· {item.title} <span className="opacity-60">({item.category})</span></li>
                ))}
              </ul>
              <p className="text-sm text-text-secondary mb-5">Add anyway?</p>
              <div className="flex gap-3">
                <button onClick={() => setShowMismatchConfirm(false)}
                  className="flex-1 border border-border-default rounded-full py-2 text-sm hover:bg-surface-hover transition-colors">
                  Cancel
                </button>
                <button onClick={commitAdd}
                  className="flex-1 bg-brand text-page rounded-full py-2 text-sm font-medium hover:bg-brand-hover transition-colors">
                  Add Anyway
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
