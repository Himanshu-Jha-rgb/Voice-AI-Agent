import { useState } from 'react';
import { useSession, useAgent } from '@livekit/components-react';
import { TokenSource } from 'livekit-client';
import { AgentSessionProvider } from '@/components/agents-ui/agent-session-provider';
import { AgentControlBar } from '@/components/agents-ui/agent-control-bar';
import { AgentChatTranscript } from '@/components/agents-ui/agent-chat-transcript';
import { AgentAudioVisualizerBar } from '@/components/agents-ui/agent-audio-visualizer-bar';
import { StartAudioButton } from '@/components/agents-ui/start-audio-button';
import { LanguageBar } from '@/components/LanguageBar';
import { useTranscripts } from '@/hooks/useTranscripts';

const tokenSource = TokenSource.endpoint('/token');

function AgentUI() {
  const { state: agentState } = useAgent();
  const { messages, detectedLanguage } = useTranscripts();
  const [isChatOpen, setIsChatOpen] = useState(false);

  return (
    <div className="flex flex-col items-center gap-6 w-full max-w-md mx-auto p-4">
      <div className="text-center">
        <h1 className="text-xl font-bold tracking-tight">School Voice AI Agent</h1>
        <p className="text-xs text-muted-foreground mt-1">
          Multilingual assistant for Indian schools — powered by Sarvam AI
        </p>
      </div>

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
        isChatOpen={isChatOpen}
        onIsChatOpenChange={setIsChatOpen}
        controls={{
          microphone: true,
          camera: false,
          screenShare: false,
          chat: false,
          leave: true,
        }}
      />

      <StartAudioButton />
    </div>
  );
}

export default function App() {
  const session = useSession(tokenSource);

  return (
    <AgentSessionProvider session={session}>
      <AgentUI />
    </AgentSessionProvider>
  );
}
