import React from 'react';
import { motion } from 'framer-motion';

const EMPTY_IMG = 'https://static.prod-images.emergentagent.com/jobs/7ecda9fa-840f-42b6-a697-5367aaabdf99/images/b9370ac7a695e13be9089e6c1701ad85ce649297b1ebeea820a9aa63696bddb3.png';

export default function EmptyState({ title, message, actionLabel, onAction }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center py-16 md:py-24 text-center px-6"
      data-testid="empty-state"
    >
      <img
        src={EMPTY_IMG}
        alt="Empty state"
        className="w-48 h-48 md:w-64 md:h-64 mb-8 object-contain drop-shadow-sm"
      />
      <h3 className="text-xl md:text-2xl font-heading font-semibold text-text-primary mb-3">
        {title}
      </h3>
      <p className="text-text-secondary max-w-md mx-auto leading-relaxed mb-6">
        {message}
      </p>
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          data-testid="empty-state-action"
          className="bg-brand text-page rounded-full px-8 py-3 font-medium hover:bg-brand-hover transition-all duration-300 shadow-[0_2px_10px_rgba(195,107,88,0.2)]"
        >
          {actionLabel}
        </button>
      )}
    </motion.div>
  );
}
