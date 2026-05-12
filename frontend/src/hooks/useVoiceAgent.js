import { useState, useRef, useCallback } from 'react';
import { Room, RoomEvent } from 'livekit-client';

const TOKEN_URL = `http://${window.location.hostname}:8000/token`;
const ROOM_NAME = 'school-voice-room';

export default function useVoiceAgent() {
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [agentState, setAgentState] = useState('idle'); // idle | listening | thinking | speaking
  const [messages, setMessages] = useState([]);
  const [detectedLanguage, setDetectedLanguage] = useState(null);
  const [error, setError] = useState(null);
  const [muted, setMuted] = useState(false);

  const roomRef = useRef(null);

  const connect = useCallback(async () => {
    setConnecting(true);
    setError(null);
    setAgentState('listening');
    setMessages([]);

    try {
      // Step 1 — fetch token
      let resp;
      try {
        resp = await fetch(`${TOKEN_URL}?room_name=${ROOM_NAME}`);
      } catch {
        throw new Error('TOKEN_SERVER_UNREACHABLE');
      }

      if (!resp.ok) {
        throw new Error(`TOKEN_SERVER_ERROR:${resp.status}`);
      }
      const data = await resp.json();

      // Step 2 — connect to LiveKit
      const room = new Room({ adaptiveStream: true, dynacast: true });
      roomRef.current = room;

      room.on(RoomEvent.Connected, () => {
        setConnected(true);
        setConnecting(false);
        setError(null);
        setAgentState('listening');
      });

      room.on(RoomEvent.Disconnected, () => {
        setConnected(false);
        setAgentState('idle');
        setDetectedLanguage(null);
      });

      room.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === 'audio') {
          const el = track.attach();
          el.muted = false;
          setAgentState('speaking');
          track.on('muted', () => {
            setAgentState((prev) => (prev === 'speaking' ? 'listening' : prev));
          });
        }
      });

      room.on(RoomEvent.DataReceived, (payload) => {
        try {
          const msg = JSON.parse(new TextDecoder().decode(payload));
          if (msg.type === 'transcript') {
            if (msg.role === 'user' && msg.text) {
              setMessages((prev) => [...prev, { role: 'user', text: msg.text }]);
              setAgentState('thinking');
            }
            if (msg.role === 'agent' && msg.text) {
              setMessages((prev) => [...prev, { role: 'agent', text: msg.text }]);
              setAgentState('speaking');
            }
            if (msg.language) {
              setDetectedLanguage(msg.language);
            }
          }
        } catch { /* ignore malformed messages */ }
      });

      try {
        await room.connect(data.url, data.token);
      } catch (lkErr) {
        throw new Error(`LIVEKIT_CONNECT_FAILED:${lkErr.message || 'unknown'}`);
      }
    } catch (err) {
      setConnected(false);
      setConnecting(false);
      setAgentState('idle');

      const msg = err.message || '';
      if (msg === 'TOKEN_SERVER_UNREACHABLE') {
        setError(`
          <strong>Token server not reachable</strong> — can't reach <code>http://localhost:8000</code>
          <code>Terminal 1: uv run python server.py</code>
          Make sure the token server is running before connecting.
        `);
      } else if (msg.startsWith('TOKEN_SERVER_ERROR:')) {
        setError(`
          <strong>Token server error</strong> — HTTP ${msg.split(':')[1]}
          Check the server.py terminal for errors.
        `);
      } else if (msg.startsWith('LIVEKIT_CONNECT_FAILED:')) {
        setError(`
          <strong>LiveKit connection failed</strong> — ${msg.split(':').slice(1).join(':')}
          <code>Terminal 2: uv run python agent.py dev</code>
          Check that the agent worker is running and your LIVEKIT_URL / API keys are correct.
        `);
      } else {
        setError(`
          <strong>Connection failed</strong> — ${msg || 'unknown error'}
          <code>Terminal 1: uv run python server.py<br>
          Terminal 2: uv run python agent.py dev<br>
          Terminal 3: cd frontend && npm run dev</code>
          Then open <strong>http://localhost:3000</strong>
        `);
      }
    }
  }, []);

  const disconnect = useCallback(async () => {
    if (roomRef.current) {
      await roomRef.current.disconnect();
      roomRef.current = null;
    }
    setMessages([]);
    setAgentState('idle');
    setDetectedLanguage(null);
  }, []);

  const toggleMute = useCallback(() => {
    if (!roomRef.current) return;
    setMuted((prev) => {
      const next = !prev;
      roomRef.current.localParticipant.setMicrophoneEnabled(!next);
      return next;
    });
  }, []);

  return {
    connected,
    connecting,
    agentState,
    messages,
    detectedLanguage,
    error,
    muted,
    connect,
    disconnect,
    toggleMute,
  };
}
