const LANGUAGES = [
  { code: 'hi-IN', name: 'Hindi' },
  { code: 'ta-IN', name: 'Tamil' },
  { code: 'te-IN', name: 'Telugu' },
  { code: 'kn-IN', name: 'Kannada' },
  { code: 'ml-IN', name: 'Malayalam' },
  { code: 'mr-IN', name: 'Marathi' },
  { code: 'gu-IN', name: 'Gujarati' },
  { code: 'bn-IN', name: 'Bengali' },
  { code: 'od-IN', name: 'Odia' },
  { code: 'pa-IN', name: 'Punjabi' },
  { code: 'en-IN', name: 'English' },
];

export default function LanguageBar({ detectedLanguage }) {
  return (
    <div className="lang-bar">
      {LANGUAGES.map(({ code, name }) => (
        <span
          key={code}
          className={`lang-chip${code === detectedLanguage ? ' active' : ''}`}
        >
          {name}
        </span>
      ))}
    </div>
  );
}
