import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Send, Loader2, Globe, Library, MessageSquare } from 'lucide-react';
import { chatAPI } from '../services/api';

/**
 * Slide-in chat drawer for per-item and global library chat.
 *
 * Props:
 *   isOpen    {bool}   — controls visibility
 *   onClose   {fn}     — called when the user dismisses the drawer
 *   mode      {"item"|"library"}
 *   itemId    {string} — required when mode="item"
 *   itemTitle {string} — shown in the drawer header
 */
export default function ChatDrawer({ isOpen, onClose, mode = 'library', itemId, itemTitle }) {
  const [messages, setMessages]     = useState([]);
  const [input, setInput]           = useState('');
  const [streaming, setStreaming]   = useState(false);
  const [searchUsed, setSearchUsed] = useState('');  // last Brave query used
  const bottomRef = useRef(null);
  const inputRef  = useRef(null);

  // Auto-scroll to bottom whenever messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input when drawer opens
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 200);
    }
  }, [isOpen]);

  // Reset when mode/item changes
  useEffect(() => {
    setMessages([]);
    setInput('');
    setSearchUsed('');
  }, [mode, itemId]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || streaming) return;

    const userMsg = { role: 'user', content: text };
    const updated = [...messages, userMsg];
    setMessages(updated);
    setInput('');
    setStreaming(true);
    setSearchUsed('');

    // Placeholder assistant message that we'll stream into
    const assistantMsg = { role: 'assistant', content: '' };
    setMessages(prev => [...prev, assistantMsg]);

    try {
      const resp = mode === 'item'
        ? await chatAPI.streamItemChat(itemId, updated)
        : await chatAPI.streamLibraryChat(updated);

      if (!resp.ok) {
        throw new Error(`Server error ${resp.status}`);
      }

      const reader  = resp.body.getReader();
      const decoder = new TextDecoder();
      let   buffer  = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep incomplete line in buffer

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
            // evt.type === 'done' — nothing extra needed
          } catch { /* skip malformed SSE line */ }
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
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 0.3 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black z-40"
          />

          {/* Drawer */}
          <motion.div
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 28, stiffness: 280 }}
            className="fixed right-0 top-0 h-full w-full sm:w-[420px] bg-white shadow-2xl z-50 flex flex-col"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-border-default">
              <div className="flex items-center gap-2.5">
                <MessageSquare className="w-4 h-4 text-brand" />
                <div>
                  <p className="text-sm font-semibold text-text-primary">
                    {mode === 'item' ? 'Ask AI' : 'Library Chat'}
                  </p>
                  {mode === 'item' && itemTitle && (
                    <p className="text-[11px] text-text-secondary truncate max-w-[260px]">
                      {itemTitle}
                    </p>
                  )}
                  {mode === 'library' && (
                    <p className="text-[11px] text-text-secondary flex items-center gap-1">
                      <Library className="w-3 h-3" /> Your entire library
                    </p>
                  )}
                </div>
              </div>
              <button
                onClick={onClose}
                className="p-2 rounded-full hover:bg-surface-hover transition-colors"
              >
                <X className="w-4 h-4 text-text-secondary" />
              </button>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
              {messages.length === 0 && (
                <div className="text-center py-12">
                  <MessageSquare className="w-8 h-8 text-text-secondary opacity-40 mx-auto mb-3" />
                  <p className="text-sm text-text-secondary">
                    {mode === 'item'
                      ? 'Ask anything about this content…'
                      : 'Ask about your saved library…'}
                  </p>
                  <div className="mt-4 space-y-1.5">
                    {(mode === 'item'
                      ? ['What are the key takeaways?', 'Summarise the steps', 'What places are mentioned?']
                      : ['Which saved videos mention travel?', 'Show me my fitness content', 'What recipes have I saved?']
                    ).map(hint => (
                      <button
                        key={hint}
                        onClick={() => { setInput(hint); inputRef.current?.focus(); }}
                        className="block w-full text-left px-3 py-2 rounded-lg text-xs text-text-secondary hover:bg-surface-hover transition-colors"
                      >
                        {hint}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((msg, i) => (
                <div
                  key={i}
                  className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[85%] px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap
                      ${msg.role === 'user'
                        ? 'bg-brand text-white rounded-br-sm'
                        : msg.error
                          ? 'bg-red-50 text-red-700 border border-red-100 rounded-bl-sm'
                          : 'bg-surface-hover text-text-primary rounded-bl-sm'
                      }`}
                  >
                    {msg.content || (streaming && i === messages.length - 1
                      ? <span className="inline-flex gap-1"><span className="w-1 h-1 rounded-full bg-text-secondary animate-bounce" /><span className="w-1 h-1 rounded-full bg-text-secondary animate-bounce [animation-delay:0.15s]" /><span className="w-1 h-1 rounded-full bg-text-secondary animate-bounce [animation-delay:0.3s]" /></span>
                      : null
                    )}
                  </div>
                </div>
              ))}

              {/* Web search indicator */}
              {searchUsed && (
                <div className="flex items-center gap-1.5 text-[11px] text-text-secondary">
                  <Globe className="w-3 h-3" />
                  <span>Web searched: <em>{searchUsed}</em></span>
                </div>
              )}

              <div ref={bottomRef} />
            </div>

            {/* Input */}
            <div className="px-4 py-3 border-t border-border-default">
              <div className="flex items-end gap-2 bg-surface-hover rounded-2xl px-3.5 py-2.5">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={mode === 'item' ? 'Ask about this content…' : 'Ask about your library…'}
                  rows={1}
                  className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-secondary resize-none outline-none max-h-24 overflow-y-auto"
                  style={{ lineHeight: '1.5' }}
                />
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || streaming}
                  className="flex-shrink-0 p-1.5 rounded-full bg-brand text-white hover:bg-brand-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {streaming
                    ? <Loader2 className="w-4 h-4 animate-spin" />
                    : <Send className="w-4 h-4" />
                  }
                </button>
              </div>
              <p className="text-[10px] text-text-secondary mt-1.5 text-center opacity-60">
                Press Enter to send · Shift+Enter for new line
              </p>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
