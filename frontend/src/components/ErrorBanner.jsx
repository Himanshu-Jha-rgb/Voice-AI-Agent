export default function ErrorBanner({ message }) {
  if (!message) return null;

  return (
    <div className="error-banner" dangerouslySetInnerHTML={{ __html: message }} />
  );
}
