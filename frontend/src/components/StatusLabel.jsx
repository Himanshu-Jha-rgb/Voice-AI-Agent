const LABELS = {
  idle: 'Tap Connect to start',
  listening: 'Listening...',
  thinking: 'Thinking...',
  speaking: 'Speaking...',
};

export default function StatusLabel({ state = 'idle' }) {
  const cls = state !== 'idle' ? `status-label ${state}` : 'status-label';
  return <div className={cls}>{LABELS[state] || ''}</div>;
}
