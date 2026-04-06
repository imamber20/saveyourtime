import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ExternalLink, CheckCircle, AlertCircle, RefreshCw, VideoOff } from 'lucide-react';
import { itemsAPI } from '../services/api';

const MAX_RETRIES = 3;

const PLATFORM_COLORS = {
  instagram: 'bg-gradient-to-br from-purple-500 to-pink-500',
  youtube: 'bg-red-600',
  facebook: 'bg-blue-600',
};

const PLATFORM_LABELS = {
  instagram: 'Instagram',
  youtube: 'YouTube',
  facebook: 'Facebook',
};

const VIDEO_PLACEHOLDER = 'https://static.prod-images.emergentagent.com/jobs/7ecda9fa-840f-42b6-a697-5367aaabdf99/images/54cc39fbc674b1e47eb9c19e535e10a091317d4c51804e073bbaf99dac7b9666.png';

// ── Skeleton card shown while a video is being processed ─────────────────────
export function ProcessingCard({ item, index = 0 }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.05 }}
      className="bg-white border border-border-default rounded-2xl shadow-sm overflow-hidden"
    >
      {/* Animated skeleton thumbnail */}
      <div className="relative aspect-[9/16] bg-surface-hover overflow-hidden">
        {/* Shimmer sweep */}
        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/50 to-transparent animate-[shimmer_1.5s_infinite]" />

        {/* Platform badge */}
        {item?.platform && (
          <div className="absolute top-3 left-3">
            <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[10px] uppercase tracking-wider font-semibold text-white ${PLATFORM_COLORS[item.platform] || 'bg-text-secondary'}`}>
              {PLATFORM_LABELS[item.platform] || item.platform}
            </span>
          </div>
        )}

        {/* Pulsing processing badge */}
        <div className="absolute top-3 right-3">
          <span className="flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-yellow-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-3 w-3 bg-yellow-500" />
          </span>
        </div>

        {/* Bottom skeleton lines */}
        <div className="absolute bottom-0 left-0 right-0 p-3 space-y-2">
          <div className="h-3 bg-white/30 rounded-full w-4/5 animate-pulse" />
          <div className="h-2 bg-white/20 rounded-full w-2/5 animate-pulse" />
        </div>
      </div>

      {/* Processing label */}
      <div className="px-3 py-2.5">
        <div className="flex items-center gap-1.5">
          <span className="flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-2 w-2 rounded-full bg-yellow-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-yellow-500" />
          </span>
          <span className="text-xs text-yellow-600 font-medium">Analysing content…</span>
        </div>
      </div>
    </motion.div>
  );
}

// ── Unavailable / removed content card ───────────────────────────────────────
export function UnavailableCard({ item, index = 0 }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.05 }}
      className="bg-white border border-border-default rounded-2xl shadow-sm overflow-hidden"
    >
      {/* Graphic area */}
      <div className="relative aspect-[9/16] overflow-hidden bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex flex-col items-center justify-center gap-3 px-4">
        {/* Scan-line overlay */}
        <div className="absolute inset-0 opacity-10"
          style={{ backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(255,255,255,0.15) 3px, rgba(255,255,255,0.15) 4px)' }}
        />

        {/* Platform badge */}
        {item?.platform && (
          <div className="absolute top-3 left-3">
            <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[10px] uppercase tracking-wider font-semibold text-white ${PLATFORM_COLORS[item.platform] || 'bg-text-secondary'}`}>
              {PLATFORM_LABELS[item.platform] || item.platform}
            </span>
          </div>
        )}

        {/* Broken screen icon */}
        <div className="relative">
          <div className="w-16 h-16 rounded-2xl bg-slate-700/60 border border-slate-600/40 flex items-center justify-center">
            <VideoOff className="w-8 h-8 text-slate-400" />
          </div>
          {/* Glitch lines */}
          <div className="absolute -top-1 left-2 right-4 h-0.5 bg-red-400/50 rounded" />
          <div className="absolute -bottom-1 left-4 right-2 h-0.5 bg-red-400/30 rounded" />
        </div>

        {/* 404 */}
        <div className="text-center">
          <p className="text-4xl font-black text-white/20 tracking-widest font-mono leading-none">404</p>
          <p className="text-xs font-semibold text-slate-300 uppercase tracking-widest mt-1">Content Unavailable</p>
          <p className="text-[10px] text-slate-500 mt-1.5 leading-snug max-w-[120px] mx-auto">
            This video was removed or is no longer accessible.
          </p>
        </div>
      </div>

      {/* Footer */}
      <div className="px-3 py-2.5">
        {item?.title ? (
          <p className="text-xs text-text-secondary truncate">{item.title}</p>
        ) : (
          <p className="text-xs text-text-secondary italic">Unknown title</p>
        )}
      </div>
    </motion.div>
  );
}

// ── Normal item card ──────────────────────────────────────────────────────────
export default function ItemCard({ item, index = 0, onRetry }) {
  const navigate = useNavigate();
  const [retrying, setRetrying] = useState(false);
  const [localStatus, setLocalStatus] = useState(item.source_status);

  // Show skeleton while processing
  if (localStatus === 'processing') {
    return <ProcessingCard item={item} index={index} />;
  }

  // Show 404 tile for removed / inaccessible content
  if (localStatus === 'unavailable') {
    return <UnavailableCard item={item} index={index} />;
  }

  const isFailed = localStatus === 'failed';
  const retryCount = item.retry_count ?? 0;
  const retriesExhausted = retryCount >= MAX_RETRIES;

  const handleRetry = async (e) => {
    e.stopPropagation();
    setRetrying(true);
    try {
      await itemsAPI.retry(item.id);
      setLocalStatus('processing');
      onRetry?.();
    } catch {
      // silently ignore — item detail page shows error state
    } finally {
      setRetrying(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.05 }}
      onClick={() => navigate(`/items/${item.id}`)}
      className="bg-white border border-border-default rounded-2xl shadow-sm overflow-hidden cursor-pointer group transition-all duration-300 hover:-translate-y-1 hover:border-sage hover:shadow-md"
      data-testid={`item-card-${item.id}`}
    >
      {/* Thumbnail */}
      <div className="relative aspect-[9/16] bg-surface-hover overflow-hidden">
        <img
          src={item.thumbnail_url || VIDEO_PLACEHOLDER}
          alt={item.title || 'Content'}
          className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
          onError={(e) => { e.target.src = VIDEO_PLACEHOLDER; }}
        />
        {/* Gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent" />

        {/* Platform badge */}
        <div className="absolute top-3 left-3">
          <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[10px] uppercase tracking-wider font-semibold text-white ${PLATFORM_COLORS[item.platform] || 'bg-text-secondary'}`}>
            {PLATFORM_LABELS[item.platform] || item.platform}
          </span>
        </div>

        {/* Status + Reload button */}
        <div className="absolute top-3 right-3 flex items-center gap-1.5">
          {/* Reload button */}
          {retriesExhausted ? (
            <span title="Max retries reached"
              className={`p-1 rounded-full bg-black/40 backdrop-blur-sm ${isFailed ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}>
              <RefreshCw className="w-3.5 h-3.5 text-slate-400 line-through" />
            </span>
          ) : (
            <button
              onClick={handleRetry}
              disabled={retrying}
              title={`Reload & reprocess (${MAX_RETRIES - retryCount} left)`}
              className={`p-1 rounded-full bg-black/40 backdrop-blur-sm transition-all ${
                isFailed ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
              } hover:bg-black/60 disabled:opacity-50`}
            >
              <RefreshCw className={`w-3.5 h-3.5 text-white ${retrying ? 'animate-spin' : ''}`} />
            </button>
          )}
          {isFailed ? (
            <AlertCircle className="w-4 h-4 text-red-400" />
          ) : (
            <CheckCircle className="w-4 h-4 text-green-400" />
          )}
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
      </div>

      {/* Tags */}
      {item.tags && item.tags.length > 0 && (
        <div className="px-3 py-2.5 flex flex-wrap gap-1.5">
          {item.tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wider font-medium bg-surface-hover text-text-secondary border border-border-default"
            >
              {tag}
            </span>
          ))}
        </div>
      )}
    </motion.div>
  );
}
