import React from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ExternalLink, Clock, CheckCircle, AlertCircle, RefreshCw } from 'lucide-react';

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

const STATUS_ICONS = {
  processing: Clock,
  completed: CheckCircle,
  failed: AlertCircle,
};

const VIDEO_PLACEHOLDER = 'https://static.prod-images.emergentagent.com/jobs/7ecda9fa-840f-42b6-a697-5367aaabdf99/images/54cc39fbc674b1e47eb9c19e535e10a091317d4c51804e073bbaf99dac7b9666.png';

export default function ItemCard({ item, index = 0 }) {
  const navigate = useNavigate();
  const StatusIcon = STATUS_ICONS[item.source_status] || Clock;

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

        {/* Status badge */}
        <div className="absolute top-3 right-3">
          <StatusIcon className={`w-4 h-4 ${
            item.source_status === 'completed' ? 'text-green-400' :
            item.source_status === 'failed' ? 'text-red-400' :
            'text-yellow-400 animate-pulse'
          }`} />
        </div>

        {/* Bottom info */}
        <div className="absolute bottom-0 left-0 right-0 p-3">
          <h3 className="text-white text-sm font-semibold line-clamp-2 leading-snug">
            {item.title || 'Processing...'}
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
