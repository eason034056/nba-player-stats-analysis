export default function BetSlipLoading() {
  return (
    <div className="mx-auto max-w-6xl px-6 py-10 page-enter">
      <div className="grid gap-6 md:grid-cols-[1.15fr_0.85fr] mb-8">
        <div className="card">
          <div className="skeleton h-5 w-28 rounded-full mb-5" />
          <div className="skeleton h-10 sm:h-14 w-3/4 mb-2" />
          <div className="skeleton h-10 sm:h-14 w-1/2 mb-4" />
          <div className="skeleton h-[2px] w-20 mb-6" />
          <div className="skeleton h-4 w-full mb-2" />
          <div className="skeleton h-4 w-4/5" />
        </div>
        <div className="card">
          <div className="skeleton h-3 w-20 mb-3" />
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
              <div className="skeleton h-3 w-16 mb-2" />
              <div className="skeleton h-8 w-8 mt-2" />
            </div>
            <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
              <div className="skeleton h-3 w-16 mb-2" />
              <div className="skeleton h-4 w-14 mt-2" />
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-4">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="card">
            <div className="flex items-start gap-4">
              <div className="skeleton w-12 h-12 rounded-lg shrink-0" />
              <div className="flex-1">
                <div className="skeleton h-5 w-40 mb-2" />
                <div className="skeleton h-3 w-48 mb-4" />
                <div className="skeleton h-8 w-44 rounded-lg mb-3" />
                <div className="flex justify-between">
                  <div className="skeleton h-3 w-28" />
                  <div className="skeleton h-3 w-20" />
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
