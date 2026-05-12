import Orb from './components/Orb';
import StatusLabel from './components/StatusLabel';
import LanguageBar from './components/LanguageBar';
import ChatTranscript from './components/ChatTranscript';
import ErrorBanner from './components/ErrorBanner';
import Controls from './components/Controls';
import useVoiceAgent from './hooks/useVoiceAgent';

export default function App() {
  const {
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
  } = useVoiceAgent();

  return (
    <div className="container">
      <div className="header">
        <h1>School Voice AI Agent</h1>
        <p>Multilingual assistant for Indian schools — powered by Sarvam AI</p>
      </div>

      <Orb state={agentState} />
      <StatusLabel state={agentState} />
      <LanguageBar detectedLanguage={detectedLanguage} />
      <ChatTranscript messages={messages} />
      <ErrorBanner message={error} />
      <Controls
        connected={connected}
        connecting={connecting}
        onConnect={connect}
        onDisconnect={disconnect}
        muted={muted}
        onToggleMute={toggleMute}
      />
    </div>
  );
}
