import { useCallback, useEffect, useState } from "react";
import type { ChatSession, Message } from "../types";

const STORAGE_KEY = "historical-guide-chats";
const ACTIVE_KEY = "historical-guide-active-chat";

function createId(): string {
  return `chat_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
}

function createMessageId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
}

function makeTitle(text: string): string {
  const cleaned = text.trim().replace(/\s+/g, " ");
  if (cleaned.length <= 32) return cleaned;
  return `${cleaned.slice(0, 32)}…`;
}

function loadChats(): ChatSession[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ChatSession[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function loadActiveId(): string | null {
  return localStorage.getItem(ACTIVE_KEY);
}

function createEmptyChat(): ChatSession {
  const now = Date.now();
  return {
    id: createId(),
    title: "Nouvelle conversation",
    messages: [],
    createdAt: now,
    updatedAt: now,
  };
}

export function useChats() {
  const [chats, setChats] = useState<ChatSession[]>(() => loadChats());
  const [activeChatId, setActiveChatId] = useState<string | null>(() => {
    const stored = loadActiveId();
    const existing = loadChats();
    if (stored && existing.some((chat) => chat.id === stored)) return stored;
    return existing[0]?.id ?? null;
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(chats));
  }, [chats]);

  useEffect(() => {
    if (activeChatId) {
      localStorage.setItem(ACTIVE_KEY, activeChatId);
    }
  }, [activeChatId]);

  const activeChat = chats.find((chat) => chat.id === activeChatId) ?? null;

  const startNewChat = useCallback(() => {
    const chat = createEmptyChat();
    setChats((prev) => [chat, ...prev]);
    setActiveChatId(chat.id);
    return chat.id;
  }, []);

  const selectChat = useCallback((chatId: string) => {
    setActiveChatId(chatId);
  }, []);

  const deleteChat = useCallback(
    (chatId: string) => {
      setChats((prev) => {
        const next = prev.filter((chat) => chat.id !== chatId);
        if (activeChatId === chatId) {
          setActiveChatId(next[0]?.id ?? null);
        }
        return next;
      });
    },
    [activeChatId],
  );

  const appendMessage = useCallback(
    (chatId: string, message: Omit<Message, "id" | "createdAt">) => {
      const fullMessage: Message = {
        ...message,
        id: createMessageId(),
        createdAt: Date.now(),
      };

      setChats((prev) =>
        prev.map((chat) => {
          if (chat.id !== chatId) return chat;
          const isFirstUserMessage =
            chat.messages.length === 0 && message.role === "user";
          return {
            ...chat,
            title: isFirstUserMessage ? makeTitle(message.content) : chat.title,
            messages: [...chat.messages, fullMessage],
            updatedAt: Date.now(),
          };
        }),
      );

      return fullMessage;
    },
    [],
  );

  const ensureActiveChat = useCallback(() => {
    if (activeChat) return activeChat.id;
    return startNewChat();
  }, [activeChat, startNewChat]);

  return {
    chats,
    activeChat,
    activeChatId,
    startNewChat,
    selectChat,
    deleteChat,
    appendMessage,
    ensureActiveChat,
  };
}
