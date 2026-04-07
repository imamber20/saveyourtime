import React, { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  MessageSquare, X, Send, Loader2, Globe, Library,
  Sparkles, ChevronDown,
} from 'lucide-react';
import { chatAPI } from '../services/api';

// ─── Context-aware question generator ────────────────────────────────────────
function getItemSuggestions(item) {
  if (!item) {
    return [
      'What are the key takeaways?',
      'Summarise the main points',
      'What action should I take from this?',
    ];
  }

  const category  = (item.category  || '').toLowerCase();
  const places    = item.places      || [];
  const keyPoints = item.key_points  || [];
  const questions = [];

  // Category-specific first question
  if (category.includes('travel') || category.includes('nature') || category.includes('outdoor')) {
    questions.push('What are the must-visit spots mentioned?');
    questions.push('Any practical travel tips here?');
  } else if (category.includes('food') || category.includes('recipe')) {
    questions.push('What are all the ingredients needed?');
    questions.push('Walk me through the cooking steps');
  } else if (category.includes('fitness') || category.includes('health') || category.includes('sport')) {
    questions.push('What is the workout routine described?');
    questions.push('What health benefits are mentioned?');
  } else if (category.includes('finance') || category.includes('money') || category.includes('career')) {
    questions.push('What financial advice is given here?');
    questions.push('What are the key investment tips?');
  } else if (category.includes('tech')) {
    questions.push('How does this technology work?');
    questions.push('What are the practical use cases?');
  } else if (category.includes('fashion') || category.includes('beauty') || category.includes('skin')) {
    questions.push('What products or brands are recommended?');
    questions.push('What is the main styling technique?');
  } else if (category.includes('learn') || category.includes('educat') || category.includes('diy')) {
    questions.push('What are the step-by-step instructions?');
    questions.push('What skills can I learn from this?');
  } else {
    questions.push('What are the key takeaways?');
    questions.push('Summarise the main points');
  }

  // Third question: place or key-point specific
  if (places.length > 0) {
    const firstName = places[0].name || places[0];
    questions.push(`Tell me more about ${String(firstName).split(',')[0].trim()}`);
  } else if (keyPoints.length > 0) {
    const first = String(keyPoints[0]).slice(0, 55);
    questions.push(`Expand on: "${first}${keyPoints[0].length > 55 ? '…' : ''}"`);
  } else {
    questions.push('What should I do next after watching this?');
  }

  return questions.slice(0, 3);
}

const LIBRARY_SUGGESTIONS = [
  'Which of my saved videos mention travel?',
  'Show me my fitness & health content',
  'What food recipes have I saved?',
];

// ─── Main Component ───────────────────────────────────────────────────────────
/**
 * FloatingChat — self-contained floating chat button + compact popup.
 *
 * Props:
 *   mode        {"item"|"library"}
 *   itemId      {string}   required when mode="item"
 *   item        {object}   full item object for context-aware questions
 *   offsetRight {number}   px from right edge (default 24)
 *   offsetBottom{number}   px from bottom edge (default 24)
 */
export default function FloatingChat({
  mode       = 'library',
  itemId     = null,
  item       = null,
  offsetRight  = 24,
  offsetBottom = 24,
}) {
  const [isOpen, setIsOpen]         = useState(false);
  const [messages, setMessages]     = useState([]);
  const [input, setInput]           = useState('');
  const [streaming, setStreaming]   = useState(false);
  const [searchUsed, setSearchUsed] = useState('');
  const [dragging, setDragging]     = useState(false);

  const bottomRef  = useRef(null);
  const inputRef   = useRef(null);
  const dragStartPos = useRef({ x: 0, y: 0 });

  const suggestions = mode === 'item'
    ? getItemSuggestions(item)
    : LIBRARY_SUGGESTIONS;

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input when popup opens
  useEffect(() => {
    if (isOpen) setTimeout(() => inputRef.current?.focus(), 150);
  }, [isOpen]);

  // Reset when mode/item changes
  useEffect(() => {
    setMessages([]);
    setInput('');
    setSearchUsed('');
  }, [mode, itemId]);

  // ── Send message ────────────────────────────────────────────────────────────
  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    const userMsg = { role: 'user', content: text };
    const history = [...messages, userMsg];
    setMessages(history);
    setInput('');
    setStreaming(true);
    setSearchUsed('');

    const assistantMsg = { role: 'assistant', content: '' };
    setMessages(prev => [...prev, assistantMsg]);

    try {
      const resp = mode === 'item'
        ? await chatAPI.streamItemChat(itemId, history)
        : await chatAPI.streamLibraryChat(history);

      if (!resp.ok) throw new Error(`Server error ${resp.status}`);

      const reader  = resp.body.getReader();
      const decoder = new TextDecoder();
      let   buffer  = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            if (evt.type === 'token') {
              setMessages(prev => {
                const copy = [...prev];
                copy[copy.length - 1] = {
                  ...copy[copy.length - 1],
                  content: copy[copy.length - 1].content + evt.content,
                };
                return copy;
              });
            } else if (evt.type === 'search_used') {
              setSearchUsed(evt.query);
            }
          } catch { /* skip malformed line */ }
        }
      }
    } catch (err) {
      setMessages(prev => {
        const copy = [...prev];
        copy[copy.length - 1] = {
          ...copy[copy.length - 1],
          content: `Sorry, something went wrong: ${err.message}`,
          error: true,
        };
        return copy;
      });
    } finally {
      setStreaming(false);
    }
  }, [input, streaming, messages, mode, itemId]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  // ── Toggle: only fires if this was a tap, not a drag ───────────────────────
  const handleButtonClick = () => {
    if (!dragging) setIsOpen(o => !o);
  };

  return (
    <motion.div
      drag
      dragMomentum={false}
      dragElastic={0}
      onDragStart={(_, info) => {
        dragStartPos.current = { x: info.point.x, y: info.point.y };
        setDragging(false);
      }}
      onDrag={(_, info) => {
        const dx = Math.abs(info.point.x - dragStartPos.current.x);
        const dy = Math.abs(info.point.y - dragStartPos.current.y);
        if (dx > 4 || dy > 4) setDragging(true);
      }}
      onDragEnd={() => {
        // Keep dragging=true briefly so click doesn't fire
        setTimeout(() => setDragging(false), 100);
      }}
      style={{ position: 'fixed', bottom: offsetBottom, right: offsetRight, zIndex: 60 }}
    >
      {/* ── Chat popup ────────────────────────────────────────────────────── */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, scale: 0.85, y: 12 }}
            animate={{ opacity: 1, scale: 1,    y: 0  }}
            exit={{   opacity: 0, scale: 0.85, y: 12  }}
            transition={{ type: 'spring', damping: 24, stiffness: 300 }}
            style={{ transformOrigin: 'bottom right' }}
            className="absolute bottom-16 right-0 w-[340px] sm:w-[380px] bg-white rounded-2xl shadow-2xl border border-border-default flex flex-col overflow-hidden"
            // Prevent drag events from bubbling to the wrapper
            onPointerDown={e => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-border-default bg-brand/5">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-brand" />
                <div>
                  <p className="text-sm font-semibold text-text-primary leading-none">
                    {mode === 'item' ? 'Ask AI' : 'Library Chat'}
                  </p>
                  <p className="text-[11px] text-text-secondary mt-0.5">
                    {mode === 'item'
                      ? (item?.title ? item.title.slice(0, 40) + (item.title.length > 40 ? '…' : '') : 'About this content')
                      : (
                        <span className="flex items-center gap-1">
                          <Library className="w-3 h-3" /> Your saved library
                        </span>
                      )
                    }
                  </p>
                </div>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="p-1.5 rounded-full hover:bg-surface-hover transition-colors"
              >
                <ChevronDown className="w-4 h-4 text-text-secondary" />
              </button>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3" style={{ maxHeight: 340 }}>
              {messages.length === 0 && (
                <div className="text-center py-4">
                  <MessageSquare className="w-7 h-7 text-text-secondary opacity-30 mx-auto mb-2" />
                  <p className="text-xs text-text-secondary mb-3">
                    {mode === 'item' ? 'Ask anything about this content' : 'Search your entire library'}
                  </p>
                  <div className="space-y-1.5">
                    {suggestions.map(hint => (
                      <button
                        key={hint}
                        onClick={() => { setInput(hint); inputRef.current?.focus(); }}
                        className="block w-full text-left px-3 py-2 rounded-xl text-xs text-text-secondary bg-surface-hover hover:bg-brand/8 hover:text-brand transition-colors leading-snug"
                      >
                        {hint}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[85%] px-3 py-2 rounded-xl text-xs leading-relaxed whitespace-pre-wrap
                      ${msg.role === 'user'
                        ? 'bg-brand text-white rounded-br-sm'
                        : msg.error
                          ? 'bg-red-50 text-red-700 border border-red-100 rounded-bl-sm'
                          : 'bg-surface-hover text-text-primary rounded-bl-sm'
                      }`}
                  >
                    {msg.content || (streaming && i === messages.length - 1
                      ? (
                        <span className="inline-flex gap-0.5 py-0.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-text-secondary animate-bounce" />
                          <span className="w-1.5 h-1.5 rounded-full bg-text-secondary animate-bounce [animation-delay:0.15s]" />
                          <span className="w-1.5 h-1.5 rounded-full bg-text-secondary animate-bounce [animation-delay:0.3s]" />
                        </span>
                      )
                      : null
                    )}
                  </div>
                </div>
              ))}

              {searchUsed && (
                <div className="flex items-center gap-1.5 text-[10px] text-text-secondary">
                  <Globe className="w-3 h-3 flex-shrink-0" />
                  <span>Searched: <em>{searchUsed}</em></span>
                </div>
              )}

              <div ref={bottomRef} />
            </div>

            {/* Input */}
            <div className="px-3 py-2.5 border-t border-border-default">
              <div className="flex items-end gap-2 bg-surface-hover rounded-xl px-3 py-2">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={mode === 'item' ? 'Ask about this content…' : 'Ask your library…'}
                  rows={1}
                  className="flex-1 bg-transparent text-xs text-text-primary placeholder:text-text-secondary resize-none outline-none max-h-16 overflow-y-auto"
                  style={{ lineHeight: '1.5' }}
                />
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || streaming}
                  className="flex-shrink-0 p-1.5 rounded-full bg-brand text-white hover:bg-brand-hover disabled:opacity-40 transition-colors"
                >
                  {streaming
                    ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    : <Send    className="w-3.5 h-3.5" />
                  }
                </button>
              </div>
              <p className="text-[9px] text-text-secondary mt-1 text-center opacity-50">
                Enter to send · Shift+Enter for new line
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Floating trigger button ─────────────────────────────────────────── */}
      <motion.button
        onClick={handleButtonClick}
        whileHover={{ scale: 1.08 }}
        whileTap={{ scale: 0.95 }}
        animate={isOpen ? { rotate: 0 } : { rotate: 0 }}
        data-testid={mode === 'item' ? 'ask-ai-fab' : 'library-chat-fab'}
        aria-label={mode === 'item' ? 'Ask AI about this content' : 'Chat with your library'}
        className={`
          relative w-14 h-14 rounded-full shadow-lg flex items-center justify-center
          transition-colors duration-200
          ${isOpen
            ? 'bg-text-primary text-white'
            : 'bg-brand text-white hover:bg-brand-hover'
          }
        `}
      >
        <AnimatePresence mode="wait">
          {isOpen
            ? (
              <motion.span
                key="close"
                initial={{ opacity: 0, rotate: -90 }}
                animate={{ opacity: 1, rotate: 0   }}
                exit={{   opacity: 0, rotate:  90  }}
                transition={{ duration: 0.15 }}
              >
                <X className="w-5 h-5" />
              </motion.span>
            )
            : (
              <motion.span
                key="open"
                initial={{ opacity: 0, rotate: 90 }}
                animate={{ opacity: 1, rotate: 0  }}
                exit={{   opacity: 0, rotate: -90 }}
                transition={{ duration: 0.15 }}
              >
                <MessageSquare className="w-5 h-5" />
              </motion.span>
            )
          }
        </AnimatePresence>

        {/* Pulse ring when closed */}
        {!isOpen && (
          <span className="absolute inset-0 rounded-full animate-ping bg-brand opacity-25 pointer-events-none" />
        )}
      </motion.button>
    </motion.div>
  );
}
