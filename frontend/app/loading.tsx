export default function Loading() {
  return (
    <div className="mx-auto max-w-6xl px-6 py-10 page-enter">
      {/* Hero section skeleton */}
      <div className="grid gap-6 md:grid-cols-[1.3fr_0.7fr] mb-10">
        <div className="card">
          <div className="skeleton h-5 w-40 rounded-full mb-5" />
          <div className="skeleton h-10 sm:h-14 w-3/4 mb-4" />
          <div className="skeleton h-[2px] w-20 mb-6" />
          <div className="skeleton h-4 w-full mb-2" />
          <div className="skeleton h-4 w-4/5" />
        </div>
        <div className="card">
          <div className="skeleton h-3 w-24 mb-3" />
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
              <div className="skeleton h-3 w-12 mb-2" />
              <div className="skeleton h-8 w-10" />
            </div>
            <div className="rounded-[22px] border border-white/8 bg-white/4 p-4">
              <div className="skeleton h-3 w-12 mb-2" />
              <div className="skeleton h-4 w-16 mt-2" />
            </div>
            <div className="hidden sm:block rounded-[22px] border border-white/8 bg-white/4 p-4">
              <div className="skeleton h-3 w-12 mb-2" />
              <div className="skeleton h-4 w-14 mt-2" />
            </div>
          </div>
        </div>
      </div>

      {/* Content cards skeleton */}
      <div className="grid gap-4 md:grid-cols-2">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="card">
            <div className="flex flex-col gap-4 py-2">
              <div className="flex items-center">
                <div className="flex-1 flex justify-center">
                  <div className="skeleton w-12 h-12 rounded-lg" />
                </div>
                <div className="w-24 flex justify-center shrink-0">
                  <div className="skeleton w-12 h-12 rounded-full" />
                </div>
                <div className="flex-1 flex justify-center">
                  <div className="skeleton w-12 h-12 rounded-lg" />
                </div>
              </div>
              <div className="flex items-center">
                <div className="flex-1 flex flex-col items-center gap-2">
                  <div className="skeleton h-4 w-24" />
                  <div className="skeleton h-3 w-12" />
                </div>
                <div className="w-24 flex justify-center shrink-0">
                  <div className="skeleton h-8 w-20 rounded-full" />
                </div>
                <div className="flex-1 flex flex-col items-center gap-2">
                  <div className="skeleton h-4 w-24" />
                  <div className="skeleton h-3 w-12" />
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
