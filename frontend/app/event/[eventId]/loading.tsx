export default function EventLoading() {
  return (
    <div className="mx-auto max-w-6xl px-6 py-10 page-enter">
      <div className="skeleton h-5 w-32 rounded-full mb-6" />

      <div className="grid gap-6 md:grid-cols-[1.1fr_0.9fr] mb-8">
        <div className="card">
          <div className="skeleton h-5 w-36 rounded-full mb-5" />
          <div className="skeleton h-10 sm:h-14 w-3/4 mb-2" />
          <div className="skeleton h-10 sm:h-14 w-1/2 mb-4" />
          <div className="skeleton h-[2px] w-20 mb-6" />
          <div className="flex flex-wrap gap-3">
            <div className="skeleton h-8 w-36 rounded-full" />
            <div className="skeleton h-8 w-28 rounded-full" />
            <div className="skeleton h-8 w-28 rounded-full" />
          </div>
        </div>
        <div className="card">
          <div className="skeleton h-3 w-40 mb-4" />
          <div className="space-y-3">
            <div className="skeleton h-4 w-full" />
            <div className="skeleton h-4 w-full" />
            <div className="skeleton h-4 w-3/4" />
          </div>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2 mb-8">
        {[...Array(2)].map((_, i) => (
          <div key={i} className="card">
            <div className="skeleton h-5 w-44 mb-4" />
            <div className="space-y-3">
              {[...Array(5)].map((_, j) => (
                <div key={j} className="flex items-center gap-3">
                  <div className="skeleton w-8 h-8 rounded-full" />
                  <div className="skeleton h-4 w-32" />
                  <div className="skeleton h-5 w-16 rounded-full ml-auto" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="card mb-6">
        <div className="skeleton h-12 w-full rounded-[22px]" />
      </div>
    </div>
  );
}
