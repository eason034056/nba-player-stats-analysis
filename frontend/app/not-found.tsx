import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-4xl px-6 py-20 page-enter">
      <div className="card text-center">
        <div className="section-eyebrow mx-auto">404</div>
        <h1 className="hero-title mb-4">
          This route slipped
          <span className="text-gradient block">off the board.</span>
        </h1>
        <div className="accent-line mx-auto mb-6" />
        <p className="mx-auto mb-8 max-w-xl text-lg leading-8 text-gray">
          The page you were trying to open does not exist or has moved. Head back to the main slate and continue from there.
        </p>
        <Link href="/" className="btn-primary">
          Return Home
        </Link>
      </div>
    </div>
  );
}
