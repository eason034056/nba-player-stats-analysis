export default function Loading() {
  return (
    <div className="mx-auto max-w-6xl px-6 py-20 page-enter">
      <div className="card">
        <div className="section-eyebrow">Loading</div>
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <div className="skeleton h-6 w-32 mb-4" />
            <div className="skeleton h-20 w-full mb-3" />
            <div className="skeleton h-4 w-4/5" />
          </div>
          <div className="grid gap-3">
            <div className="skeleton h-24 w-full" />
            <div className="skeleton h-24 w-full" />
          </div>
        </div>
      </div>
    </div>
  );
}
