export default function PicksLoading() {
  return (
    <div className="mx-auto max-w-6xl px-6 py-10 page-enter">
      <div className="grid gap-6 md:grid-cols-[1.2fr_0.8fr] mb-8">
        <div className="card">
          <div className="skeleton h-5 w-32 rounded-full mb-5" />
          <div className="skeleton h-10 sm:h-14 w-2/3 mb-4" />
          <div className="skeleton h-[2px] w-20 mb-6" />
          <div className="skeleton h-4 w-full mb-2" />
          <div className="skeleton h-4 w-3/4" />
        </div>
        <div className="card">
          <div className="skeleton h-3 w-24 mb-3" />
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
              <div className="skeleton h-3 w-10 mb-2" />
              <div className="skeleton h-6 w-20 mt-2" />
            </div>
            <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
              <div className="skeleton h-3 w-10 mb-2" />
              <div className="skeleton h-6 w-8 mt-2" />
            </div>
          </div>
        </div>
      </div>

      <div className="card mb-6">
        <div className="skeleton h-12 w-full rounded-[22px]" />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="card">
            <div className="flex items-start gap-3 mb-3">
              <div className="skeleton w-10 h-10 rounded-lg shrink-0" />
              <div className="flex-1">
                <div className="skeleton h-5 w-32 mb-2" />
                <div className="skeleton h-3 w-24" />
              </div>
            </div>
            <div className="skeleton h-8 w-40 rounded-lg mb-3" />
            <div className="flex justify-between">
              <div className="skeleton h-3 w-20" />
              <div className="skeleton h-6 w-16" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
