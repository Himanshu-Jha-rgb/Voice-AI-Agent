import { useState } from 'react';
import { useSession, useAgent, type UseSessionReturn } from '@livekit/components-react';
import { TokenSource, ConnectionState } from 'livekit-client';
import { AgentSessionProvider } from '@/components/agents-ui/agent-session-provider';
import { AgentControlBar } from '@/components/agents-ui/agent-control-bar';
import { AgentChatTranscript } from '@/components/agents-ui/agent-chat-transcript';
import { AgentAudioVisualizerBar } from '@/components/agents-ui/agent-audio-visualizer-bar';
import { StartAudioButton } from '@/components/agents-ui/start-audio-button';
import { LanguageBar } from '@/components/LanguageBar';
import { useTranscripts } from '@/hooks/useTranscripts';
import { Button } from '@/components/ui/button';
import { Phone, Loader2, AlertCircle } from 'lucide-react';

const tokenSource = TokenSource.endpoint('/token');

function AgentUI({ session }: { session: UseSessionReturn }) {
  const { state: agentState } = useAgent();
  const { messages, detectedLanguage } = useTranscripts();
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isConnected =
    session.connectionState === ConnectionState.Connected ||
    session.connectionState === ConnectionState.Reconnecting;

  const isConnectingNow =
    session.connectionState === ConnectionState.Connecting;

  const handleConnect = async () => {
    setIsConnecting(true);
    setError(null);
    try {
      await session.start();
    } catch (err: any) {
      const msg = err?.message || String(err);
      if (msg.includes('Failed to fetch') || msg.includes('fetch')) {
        setError('Token server unreachable — run: uv run python server.py');
      } else if (msg.includes('401') || msg.includes('403')) {
        setError('Token server error — check your API keys in .env');
      } else {
        setError(`Connection failed: ${msg}`);
      }
      console.error('Connect error:', err);
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    await session.end();
  };

  return (
    <div className="flex flex-col items-center gap-6 w-full max-w-md mx-auto p-4">
      <div className="text-center">
        <h1 className="text-xl font-bold tracking-tight">School Voice AI Agent</h1>
        <p className="text-xs text-muted-foreground mt-1">
          Multilingual assistant for Indian schools — powered by Sarvam AI
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 w-full p-3 rounded-lg bg-destructive/10 text-destructive text-sm">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <code className="text-xs">{error}</code>
        </div>
      )}

      {!isConnected ? (
        /* ── Not connected: show connect button ── */
        <div className="flex flex-col items-center gap-4 mt-4">
          <AgentAudioVisualizerBar
            state={agentState}
            size="lg"
            className="text-primary opacity-40"
          />
          <Button
            size="lg"
            onClick={handleConnect}
            disabled={isConnecting || isConnectingNow}
            className="rounded-full px-8 gap-2"
          >
            {isConnecting || isConnectingNow ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin" />
                Connecting...
              </>
            ) : (
              <>
                <Phone className="h-5 w-5" />
                Start Call
              </>
            )}
          </Button>
          <p className="text-xs text-muted-foreground">
            Click to connect and start talking to Shubh
          </p>
        </div>
      ) : (
        /* ── Connected: show full UI ── */
        <>
          <AgentAudioVisualizerBar
            state={agentState}
            size="lg"
            className="text-primary"
          />

          <LanguageBar detectedLanguage={detectedLanguage} />

          <AgentChatTranscript
            agentState={agentState}
            messages={messages}
            className="w-full h-[300px]"
          />

          <AgentControlBar
            variant="livekit"
            isConnected={isConnected}
            isChatOpen={isChatOpen}
            onIsChatOpenChange={setIsChatOpen}
            onDisconnect={handleDisconnect}
            controls={{
              microphone: true,
              camera: false,
              screenShare: false,
              chat: false,
              leave: true,
            }}
          />

          <StartAudioButton label="Start Audio" />
        </>
      )}
    </div>
  );
}

export default function App() {
  const session = useSession(tokenSource);

  return (
    <AgentSessionProvider session={session}>
      <AgentUI session={session} />
    </AgentSessionProvider>
  );
}
