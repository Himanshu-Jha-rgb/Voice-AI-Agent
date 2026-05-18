import { cn } from '@/lib/utils';

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

interface LanguageBarProps {
  detectedLanguage: string | null;
  className?: string;
}

export function LanguageBar({ detectedLanguage, className }: LanguageBarProps) {
  return (
    <div className={cn('flex flex-wrap gap-1.5 justify-center', className)}>
      {LANGUAGES.map(({ code, name }) => (
        <span
          key={code}
          className={cn(
            'px-3 py-1 rounded-full text-xs font-medium border transition-all duration-200',
            code === detectedLanguage
              ? 'bg-green-500/15 border-green-500 text-green-500'
              : 'bg-card border-border text-muted-foreground hover:border-muted-foreground/50',
          )}
        >
          {name}
        </span>
      ))}
    </div>
  );
}
