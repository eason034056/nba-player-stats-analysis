"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto max-w-4xl px-6 py-20 page-enter">
      <div className="card">
        <div className="section-eyebrow">Application error</div>
        <h1 className="hero-title mb-4">
          Something broke
          <span className="text-gradient block">inside the workspace.</span>
        </h1>
        <div className="accent-line mb-6" />
        <p className="mb-3 text-lg text-gray">
          The page could not finish rendering. Try the action again, or move back to a stable route.
        </p>
        <p className="mb-8 text-sm text-light">
          {error.message}
        </p>
        <div className="flex flex-wrap gap-3">
          <button type="button" onClick={reset} className="btn-primary">
            Try Again
          </button>
          <a href="/" className="btn-refresh">
            Back to Home
          </a>
        </div>
      </div>
    </div>
  );
}
