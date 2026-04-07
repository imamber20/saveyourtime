import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { itemsAPI, collectionsAPI, placesAPI, formatApiErrorDetail } from '../services/api';
import { supabase } from '../services/supabase';
import ChatDrawer from '../components/ChatDrawer';
import {
  ArrowLeft, ExternalLink, Edit3, Trash2, RefreshCw, MapPin, Tag,
  Clock, CheckCircle, AlertCircle, FolderPlus, Loader2,
  List, ChefHat, Footprints, PenLine, Check, X, MessageSquare
} from 'lucide-react';

const VIDEO_PLACEHOLDER = 'https://static.prod-images.emergentagent.com/jobs/7ecda9fa-840f-42b6-a697-5367aaabdf99/images/54cc39fbc674b1e47eb9c19e535e10a091317d4c51804e073bbaf99dac7b9666.png';

const PLATFORM_LABELS = { instagram: 'Instagram', youtube: 'YouTube', facebook: 'Facebook' };

export default function ItemDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [collections, setCollections] = useState([]);
  const [showCollPicker, setShowCollPicker] = useState(false);
  const [error, setError] = useState('');
  const realtimeChannelRef = useRef(null);
  const [correctingPlaceId, setCorrectingPlaceId] = useState(null);
  const [correctionInput, setCorrectionInput] = useState('');
  const [correctionSaving, setCorrectionSaving] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);

  useEffect(() => {
    fetchItem();
    fetchCollections();
  }, [id]);

  // ── Supabase Realtime: watch this item for status updates ─────────────────
  // Subscribe whenever the item is in 'processing' state so the detail view
  // automatically refreshes when the backend finishes processing.
  useEffect(() => {
    if (!id) return;

    // Clean up previous channel if id changed
    if (realtimeChannelRef.current) {
      supabase.removeChannel(realtimeChannelRef.current);
      realtimeChannelRef.current = null;
    }

    const channel = supabase
      .channel(`item:detail:${id}`)
      .on(
        'postgres_changes',
        {
          event: 'UPDATE',
          schema: 'public',
          table: 'items',
          filter: `id=eq.${id}`,
        },
        (_payload) => {
          // Re-fetch from our backend (includes places, collections, etc.)
          fetchItem();
        }
      )
      .subscribe();

    realtimeChannelRef.current = channel;

    return () => {
      supabase.removeChannel(channel);
      realtimeChannelRef.current = null;
    };
  }, [id]); // intentionally omit fetchItem from deps — we only want to subscribe once per item ID

  const fetchItem = async () => {
    try {
      const { data } = await itemsAPI.get(id);
      setItem(data);
      setEditForm({
        title: data.title || '',
        summary: data.summary || '',
        category: data.category || '',
        sub_category: data.sub_category || '',
        tags: (data.tags || []).join(', '),
        notes: data.notes || '',
      });
    } catch (err) {
      setError('Item not found');
    } finally {
      setLoading(false);
    }
  };

  const fetchCollections = async () => {
    try {
      const { data } = await collectionsAPI.list();
      setCollections(data.collections || []);
    } catch {}
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = {
        title: editForm.title,
        summary: editForm.summary,
        category: editForm.category,
        sub_category: editForm.sub_category,
        tags: editForm.tags.split(',').map(t => t.trim()).filter(Boolean),
        notes: editForm.notes,
      };
      const { data } = await itemsAPI.update(id, payload);
      setItem(prev => ({ ...prev, ...data }));
      setEditing(false);
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('Delete this item?')) return;
    try {
      await itemsAPI.delete(id);
      navigate('/');
    } catch {}
  };

  const handleRetry = async () => {
    try {
      await itemsAPI.retry(id);
      fetchItem();
    } catch {}
  };

  const handleAddToCollection = async (collId) => {
    try {
      await collectionsAPI.addItem(collId, id);
      setShowCollPicker(false);
      fetchItem();
    } catch {}
  };

  const handleSaveCorrection = async (placeId) => {
    const addr = correctionInput.trim();
    if (!addr) return;
    setCorrectionSaving(true);
    try {
      await placesAPI.correct(placeId, addr);
      setCorrectingPlaceId(null);
      setCorrectionInput('');
      fetchItem(); // refresh to show new coords
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || 'Could not geocode that address');
    } finally {
      setCorrectionSaving(false);
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center py-20">
      <Loader2 className="w-8 h-8 text-brand animate-spin" />
    </div>
  );

  if (error && !item) return (
    <div className="text-center py-20">
      <p className="text-text-secondary">{error}</p>
      <button onClick={() => navigate('/')} className="mt-4 text-brand hover:underline">Go home</button>
    </div>
  );

  if (!item) return null;

  const MAX_RETRIES = 3;
  const retryCount = item.retry_count ?? 0;
  const retriesExhausted = retryCount >= MAX_RETRIES;
  const canRetry = ['failed', 'completed', 'unavailable'].includes(item.source_status) && !retriesExhausted;

  const StatusIcon = item.source_status === 'completed' ? CheckCircle :
                     item.source_status === 'failed' ? AlertCircle : Clock;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      data-testid="item-detail-page"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <button
          onClick={() => navigate(-1)}
          data-testid="back-button"
          className="flex items-center gap-2 text-text-secondary hover:text-text-primary transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          <span className="text-sm font-medium">Back</span>
        </button>
        <div className="flex items-center gap-2">
          {canRetry && (
            <button onClick={handleRetry} data-testid="retry-button"
              className="p-2.5 rounded-full border border-border-default hover:bg-surface-hover transition-colors"
              aria-label={`Reload (${MAX_RETRIES - retryCount} retries left)`}
              title={`Reload & reprocess (${MAX_RETRIES - retryCount} retries left)`}>
              <RefreshCw className="w-4 h-4 text-text-secondary" />
            </button>
          )}
          {retriesExhausted && (
            <span className="px-2.5 py-1.5 rounded-full border border-border-default text-xs text-text-secondary" title="Maximum retries reached">
              Max retries
            </span>
          )}
          <button onClick={() => setChatOpen(true)} data-testid="ask-ai-button"
            className="p-2.5 rounded-full border border-brand/30 bg-brand/5 hover:bg-brand/10 transition-colors" aria-label="Ask AI">
            <MessageSquare className="w-4 h-4 text-brand" />
          </button>
          <button onClick={() => setEditing(!editing)} data-testid="edit-button"
            className="p-2.5 rounded-full border border-border-default hover:bg-surface-hover transition-colors" aria-label="Edit">
            <Edit3 className="w-4 h-4 text-text-secondary" />
          </button>
          <button onClick={() => setShowCollPicker(!showCollPicker)} data-testid="add-to-collection-button"
            className="p-2.5 rounded-full border border-border-default hover:bg-surface-hover transition-colors" aria-label="Add to collection">
            <FolderPlus className="w-4 h-4 text-text-secondary" />
          </button>
          <button onClick={handleDelete} data-testid="delete-button"
            className="p-2.5 rounded-full border border-red-200 hover:bg-red-50 transition-colors" aria-label="Delete">
            <Trash2 className="w-4 h-4 text-red-500" />
          </button>
        </div>
      </div>

      {/* Collection picker dropdown */}
      {showCollPicker && (
        <div className="mb-4 bg-white border border-border-default rounded-xl p-4 shadow-sm" data-testid="collection-picker">
          <p className="text-sm font-medium text-text-primary mb-2">Add to collection</p>
          {collections.length === 0 ? (
            <p className="text-xs text-text-secondary">No collections yet. Create one first.</p>
          ) : (
            <div className="space-y-1">
              {collections.map(c => (
                <button key={c.id} onClick={() => handleAddToCollection(c.id)}
                  className="block w-full text-left px-3 py-2 rounded-lg text-sm hover:bg-surface-hover transition-colors">
                  {c.name}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Content */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12">
        {/* Left - Thumbnail */}
        <div className="lg:col-span-5">
          <div className="relative aspect-[9/16] rounded-2xl overflow-hidden bg-surface-hover">
            <img
              src={item.thumbnail_url || VIDEO_PLACEHOLDER}
              alt={item.title}
              className="w-full h-full object-cover"
              onError={(e) => { e.target.src = VIDEO_PLACEHOLDER; }}
            />
            <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent" />
          </div>
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="source-link"
            className="flex items-center justify-center gap-2 mt-4 px-6 py-3 bg-white border border-border-default rounded-full text-sm font-medium text-text-primary hover:border-brand hover:text-brand transition-all"
          >
            <ExternalLink className="w-4 h-4" />
            Open on {PLATFORM_LABELS[item.platform] || item.platform}
          </a>
        </div>

        {/* Right - Details */}
        <div className="lg:col-span-7 space-y-6">
          {editing ? (
            /* Edit Mode */
            <div className="space-y-4" data-testid="edit-form">
              <div>
                <label className="block text-xs uppercase tracking-wider font-semibold text-text-secondary mb-1.5">Title</label>
                <input
                  value={editForm.title}
                  onChange={(e) => setEditForm(f => ({ ...f, title: e.target.value }))}
                  data-testid="edit-title-input"
                  className="w-full px-4 py-2.5 border border-border-default rounded-xl text-sm focus:border-brand outline-none"
                />
              </div>
              <div>
                <label className="block text-xs uppercase tracking-wider font-semibold text-text-secondary mb-1.5">Summary</label>
                <textarea
                  value={editForm.summary}
                  onChange={(e) => setEditForm(f => ({ ...f, summary: e.target.value }))}
                  data-testid="edit-summary-input"
                  rows={3}
                  className="w-full px-4 py-2.5 border border-border-default rounded-xl text-sm focus:border-brand outline-none resize-none"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs uppercase tracking-wider font-semibold text-text-secondary mb-1.5">Category</label>
                  <input
                    value={editForm.category}
                    onChange={(e) => setEditForm(f => ({ ...f, category: e.target.value }))}
                    data-testid="edit-category-input"
                    className="w-full px-4 py-2.5 border border-border-default rounded-xl text-sm focus:border-brand outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs uppercase tracking-wider font-semibold text-text-secondary mb-1.5">Sub-Category</label>
                  <input
                    value={editForm.sub_category}
                    onChange={(e) => setEditForm(f => ({ ...f, sub_category: e.target.value }))}
                    data-testid="edit-subcategory-input"
                    className="w-full px-4 py-2.5 border border-border-default rounded-xl text-sm focus:border-brand outline-none"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs uppercase tracking-wider font-semibold text-text-secondary mb-1.5">Tags (comma separated)</label>
                <input
                  value={editForm.tags}
                  onChange={(e) => setEditForm(f => ({ ...f, tags: e.target.value }))}
                  data-testid="edit-tags-input"
                  className="w-full px-4 py-2.5 border border-border-default rounded-xl text-sm focus:border-brand outline-none"
                />
              </div>
              <div>
                <label className="block text-xs uppercase tracking-wider font-semibold text-text-secondary mb-1.5">Notes</label>
                <textarea
                  value={editForm.notes}
                  onChange={(e) => setEditForm(f => ({ ...f, notes: e.target.value }))}
                  data-testid="edit-notes-input"
                  rows={3}
                  className="w-full px-4 py-2.5 border border-border-default rounded-xl text-sm focus:border-brand outline-none resize-none"
                />
              </div>
              <div className="flex gap-3">
                <button onClick={handleSave} disabled={saving} data-testid="save-edit-button"
                  className="bg-brand text-page rounded-full px-6 py-2.5 text-sm font-medium hover:bg-brand-hover transition-colors disabled:opacity-50">
                  {saving ? 'Saving...' : 'Save Changes'}
                </button>
                <button onClick={() => setEditing(false)} data-testid="cancel-edit-button"
                  className="bg-white border border-border-default text-text-primary rounded-full px-6 py-2.5 text-sm font-medium hover:bg-surface-hover transition-colors">
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            /* View Mode */
            <>
              {/* Status */}
              <div className="flex items-center gap-2">
                <StatusIcon className={`w-4 h-4 ${
                  item.source_status === 'completed' ? 'text-green-500' :
                  item.source_status === 'failed' ? 'text-red-500' : 'text-yellow-500'
                }`} />
                <span className="text-xs uppercase tracking-wider font-semibold text-text-secondary">
                  {item.source_status}
                </span>
                <span className="text-xs text-text-secondary">
                  {PLATFORM_LABELS[item.platform]}
                </span>
                {item.confidence_score > 0 && (
                  <span className="text-xs text-text-secondary ml-auto">
                    {Math.round(item.confidence_score * 100)}% confidence
                  </span>
                )}
              </div>

              {/* Title */}
              <h1 className="font-heading text-2xl sm:text-3xl font-semibold text-text-primary leading-tight" data-testid="item-title">
                {item.title || 'Untitled'}
              </h1>

              {/* Category & Tags */}
              <div className="flex flex-wrap items-center gap-2">
                {item.category && (
                  <span className="inline-flex items-center px-3 py-1.5 rounded-full text-xs uppercase tracking-wider font-semibold bg-brand/10 text-brand">
                    {item.category}
                  </span>
                )}
                {item.sub_category && (
                  <span className="inline-flex items-center px-3 py-1.5 rounded-full text-xs uppercase tracking-wider font-medium bg-sage/10 text-sage">
                    {item.sub_category}
                  </span>
                )}
                {(item.tags || []).map(tag => (
                  <span key={tag} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] uppercase tracking-wider font-medium bg-surface-hover text-text-secondary border border-border-default">
                    <Tag className="w-3 h-3" />{tag}
                  </span>
                ))}
              </div>

              {/* Summary */}
              {item.summary && (
                <div>
                  <h3 className="text-xs uppercase tracking-wider font-semibold text-text-secondary mb-2">Summary</h3>
                  <p className="text-text-primary leading-relaxed" data-testid="item-summary">{item.summary}</p>
                </div>
              )}

              {/* Key Points */}
              {item.key_points && item.key_points.length > 0 && (
                <div>
                  <h3 className="text-xs uppercase tracking-wider font-semibold text-text-secondary mb-2 flex items-center gap-1.5">
                    <List className="w-3.5 h-3.5" /> Key Points
                  </h3>
                  <ul className="space-y-1.5">
                    {item.key_points.map((pt, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-text-primary leading-relaxed">
                        <span className="mt-1.5 flex-shrink-0 w-1.5 h-1.5 rounded-full bg-brand" />
                        {pt}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Ingredients */}
              {item.ingredients && item.ingredients.length > 0 && (
                <div>
                  <h3 className="text-xs uppercase tracking-wider font-semibold text-text-secondary mb-2 flex items-center gap-1.5">
                    <ChefHat className="w-3.5 h-3.5" /> Ingredients
                  </h3>
                  <ul className="grid grid-cols-2 gap-x-4 gap-y-1">
                    {item.ingredients.map((ing, i) => (
                      <li key={i} className="flex items-center gap-1.5 text-sm text-text-primary">
                        <span className="w-1 h-1 rounded-full bg-accent flex-shrink-0" />
                        {ing}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Steps / Instructions */}
              {item.steps && item.steps.length > 0 && (
                <div>
                  <h3 className="text-xs uppercase tracking-wider font-semibold text-text-secondary mb-2 flex items-center gap-1.5">
                    <Footprints className="w-3.5 h-3.5" /> Steps
                  </h3>
                  <ol className="space-y-2">
                    {item.steps.map((step, i) => (
                      <li key={i} className="flex items-start gap-3 text-sm text-text-primary leading-relaxed">
                        <span className="flex-shrink-0 w-5 h-5 rounded-full bg-brand/10 text-brand text-[10px] font-bold flex items-center justify-center mt-0.5">
                          {i + 1}
                        </span>
                        {step.replace(/^step\s*\d+[:\-\s]*/i, '')}
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              {/* Notes */}
              {item.notes && (
                <div>
                  <h3 className="text-xs uppercase tracking-wider font-semibold text-text-secondary mb-2">Notes</h3>
                  <p className="text-text-primary leading-relaxed">{item.notes}</p>
                </div>
              )}

              {/* Places */}
              {item.places && item.places.length > 0 && (
                <div>
                  <h3 className="text-xs uppercase tracking-wider font-semibold text-text-secondary mb-2">Places</h3>
                  <div className="flex flex-col gap-2">
                    {item.places.map(place => (
                      <div key={place.id}>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => place.latitude && place.longitude
                              ? navigate(`/map?flyTo=${place.latitude},${place.longitude}`)
                              : navigate('/map')
                            }
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-brand/10 text-brand text-sm font-medium hover:bg-brand/20 transition-colors"
                          >
                            <MapPin className="w-3.5 h-3.5" />
                            {place.name}
                          </button>
                          {/* Correction toggle */}
                          <button
                            onClick={() => {
                              if (correctingPlaceId === place.id) {
                                setCorrectingPlaceId(null);
                                setCorrectionInput('');
                              } else {
                                setCorrectingPlaceId(place.id);
                                setCorrectionInput(place.address || '');
                              }
                            }}
                            title="Suggest address correction"
                            className="p-1 rounded-full text-text-secondary hover:text-brand hover:bg-brand/10 transition-colors"
                          >
                            <PenLine className="w-3.5 h-3.5" />
                          </button>
                          {place.geocode_source && (
                            <span className="text-[10px] text-text-secondary opacity-60">
                              via {place.geocode_source}
                            </span>
                          )}
                        </div>

                        {/* Inline correction input */}
                        {correctingPlaceId === place.id && (
                          <div className="mt-2 ml-1 flex items-center gap-2">
                            <input
                              autoFocus
                              value={correctionInput}
                              onChange={e => setCorrectionInput(e.target.value)}
                              onKeyDown={e => {
                                if (e.key === 'Enter') handleSaveCorrection(place.id);
                                if (e.key === 'Escape') { setCorrectingPlaceId(null); setCorrectionInput(''); }
                              }}
                              placeholder="Enter correct address…"
                              className="flex-1 px-3 py-1.5 border border-border-default rounded-lg text-xs focus:border-brand outline-none"
                            />
                            <button
                              onClick={() => handleSaveCorrection(place.id)}
                              disabled={correctionSaving}
                              className="p-1.5 rounded-lg bg-brand text-white hover:bg-brand-hover disabled:opacity-50 transition-colors"
                            >
                              {correctionSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                            </button>
                            <button
                              onClick={() => { setCorrectingPlaceId(null); setCorrectionInput(''); }}
                              className="p-1.5 rounded-lg border border-border-default hover:bg-surface-hover transition-colors"
                            >
                              <X className="w-3.5 h-3.5 text-text-secondary" />
                            </button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Collections */}
              {item.collections && item.collections.length > 0 && (
                <div>
                  <h3 className="text-xs uppercase tracking-wider font-semibold text-text-secondary mb-2">Collections</h3>
                  <div className="flex flex-wrap gap-2">
                    {item.collections.map(c => (
                      <span key={c.id} className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-surface-hover text-text-secondary border border-border-default">
                        {c.name}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Per-item AI chat drawer */}
      <ChatDrawer
        isOpen={chatOpen}
        onClose={() => setChatOpen(false)}
        mode="item"
        itemId={id}
        itemTitle={item?.title}
      />
    </motion.div>
  );
}
