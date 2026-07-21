import React, { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { Send, MessageCircle } from "lucide-react";

export default function ChatSidebar() {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const scrollRef = useRef(null);

  const load = async () => {
    try {
      const { data } = await api.get("/chat/messages", { params: { limit: 50 } });
      setMessages(data);
    } catch {}
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const send = async (e) => {
    e.preventDefault();
    if (!user) {
      toast.info("Log in to chat");
      return;
    }
    if (!text.trim()) return;
    setSending(true);
    try {
      await api.post("/chat/messages", { message: text.trim() });
      setText("");
      await load();
    } catch (e2) {
      toast.error(e2?.response?.data?.detail || "Failed to send");
    } finally {
      setSending(false);
    }
  };

  return (
    <aside className="sd-panel flex flex-col h-full" data-testid="chat-sidebar">
      <div
        className="flex items-center justify-between px-4 py-3 border-b border-[color:var(--sd-lavender-2)]"
      >
        <div className="flex items-center gap-2 font-black tracking-widest text-sm text-[color:var(--sd-purple-deep)]">
          <MessageCircle className="w-4 h-4" />
          CHAT
        </div>
        <div className="text-xs text-muted-foreground font-bold">
          {messages.length} msgs
        </div>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-3 py-2 space-y-2 min-h-[280px] max-h-[520px]"
        data-testid="chat-messages"
      >
        {messages.length === 0 && (
          <div className="text-center text-xs text-muted-foreground py-10">
            No messages yet. Say hi!
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className="text-sm" data-testid="chat-message">
            <span className="font-black text-[color:var(--sd-purple-deep)]">{m.username}</span>
            <span className="mx-1 text-muted-foreground">›</span>
            <span className="text-[color:#1a3d2c]">{m.message}</span>
          </div>
        ))}
      </div>

      <form onSubmit={send} className="p-3 border-t border-[color:var(--sd-lavender-2)] flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={user ? "Type message..." : "Log in to chat"}
          disabled={!user || sending}
          maxLength={280}
          data-testid="chat-input"
          className="flex-1 rounded-full bg-[color:var(--sd-lavender)] px-4 py-2 text-sm outline-none focus:ring-2 focus:ring-[color:var(--sd-purple)]"
        />
        <button
          type="submit"
          disabled={!user || sending || !text.trim()}
          data-testid="chat-send"
          className="rounded-full bg-[color:var(--sd-purple)] text-white w-10 h-10 flex items-center justify-center hover:bg-[color:var(--sd-purple-dark)] disabled:opacity-50"
        >
          <Send className="w-4 h-4" />
        </button>
      </form>
    </aside>
  );
}
