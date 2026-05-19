import { useEffect, useState, useCallback } from 'react';
import { RoomEvent } from 'livekit-client';
import { useRoomContext } from '@livekit/components-react';

export interface TranscriptMessage {
  id: string;
  timestamp: number;
  from: { isLocal: boolean } | undefined;
  message: string;
}

/**
 * Custom hook that listens to LiveKit data channel messages
 * from the Voice-AI-Agent (format: { type: "transcript", role, text, language }).
 * Returns messages in a format compatible with AgentChatTranscript.
 */
export function useTranscripts() {
  const room = useRoomContext();
  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [detectedLanguage, setDetectedLanguage] = useState<string | null>(null);

  const reset = useCallback(() => {
    setMessages([]);
    setDetectedLanguage(null);
  }, []);

  useEffect(() => {
    if (!room) return;

    const handleData = (payload: Uint8Array) => {
      try {
        const msg = JSON.parse(new TextDecoder().decode(payload));
        if (msg.type !== 'transcript' || !msg.text) return;

        const transcript: TranscriptMessage = {
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          timestamp: Date.now(),
          from: msg.role === 'user' ? { isLocal: true } : { isLocal: false },
          message: msg.text,
        };

        setMessages((prev) => [...prev, transcript]);

        if (msg.language) {
          setDetectedLanguage(msg.language);
        }
      } catch {
        // ignore malformed messages
      }
    };

    room.on(RoomEvent.DataReceived, handleData);
    return () => {
      room.off(RoomEvent.DataReceived, handleData);
    };
  }, [room]);

  // Reset when room disconnects
  useEffect(() => {
    if (!room) return;
    const handleDisconnect = () => {
      setMessages([]);
      setDetectedLanguage(null);
    };
    room.on(RoomEvent.Disconnected, handleDisconnect);
    return () => {
      room.off(RoomEvent.Disconnected, handleDisconnect);
    };
  }, [room]);

  return { messages, detectedLanguage, reset };
}
