import { useEffect, useRef } from 'react';

export default function ChatTranscript({ messages }) {
  const chatRef = useRef(null);

  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className="chat" ref={chatRef}>
      {messages.length === 0 ? (
        <div className="chat-empty">Your conversation will appear here</div>
      ) : (
        messages.map((msg, i) => (
          <div key={i} className={`chat-bubble ${msg.role}`}>
            {msg.text}
          </div>
        ))
      )}
    </div>
  );
}
